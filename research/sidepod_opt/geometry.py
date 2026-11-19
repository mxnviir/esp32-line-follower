"""Design -> legal, milled body -> CFD car folder. Everything at 1 mm on the STEP's own grid.

Frames
  STEP frame  x forward (nose at +x), y left, z up, mm  -- the team's CAD.
  car frame   x from the nose tip towards the tail, z up from the track, m -- Parts 2/4, OpenFOAM
              (flow along +x). x_car = (x_nose - x_step) / 1000.

A design is a FIELD over the sidepod region (positive = foam). Representations (methods.py) only
make fields; everything below is shared, so every method is judged on the same body:
  finish   rule zones forced to air, cargo forced to foam, spine/halo zone copied from the STEP
  mill     Part 1's machining rule (team: 3-axis, 6.35 mm ball end, setups top/bottom/left/right):
           air the ball can't clear stays foam; sealed voids stay foam; loose pieces are not made
  check    one piece, no voids, nothing changed outside the region, rule zones clear
  weigh    exact foam mass and COM; lead in the T1.22 container brings a light car to the floor
  export   watertight half-car STL (solid `car`) + wheels + assembly.json + mass_report.json
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "part1-simulation"))
import machining as MC  # noqa: E402  (Part 1: the team's milling rule)

FOAM_G_CM3 = 0.163
LEAD_G_CM3 = 11.34
WHEEL_SINK_MM = 0.3                  # as Part 4 assembly.SINK_MM: a clean wheel/road contact for snappy


@dataclass
class CarSpec:
    """Everything about the car that is not the sidepod. Defaults: the trial car STEP."""
    step: str = str(REPO / "research/sidepod_region/cad/trial_car.step")
    body_solid: str = "car_body"
    wheel_solids: tuple = ("wheel_fl", "wheel_rl", "wheel_fr", "wheel_lr")
    x_nose_mm: float = 228.625
    x_front_axle: float = 173.25
    x_rear_axle: float = 35.25
    r_wheel: float = 14.12
    front_inner_y: float = 19.25
    rear_inner_y: float = 16.25
    # region (per side, mirrored)
    region_x: tuple = (49.4, 159.1)
    region_ymax: float = 32.5            # T1.14 block half-width
    region_z: tuple = (1.5, 40.0)        # T3.7 clearance .. deck
    spine_y: float = 13.5                # |y| <= this and z >= spine_z: deck, cockpit, halo (locked)
    spine_z: float = 17.0
    halo_x0: float = 115.0               # T4.4.2: nothing above halo_zmin from here forward
    halo_zmin: float = 27.0
    cargo_x: tuple = (76.0, 136.0)       # T4.2 wedge, wide end (55 mm) forward
    cargo_z: tuple = (17.0, 27.0)        # ASSUMED: confirm with the team
    # mass (ASSUMED where the STEP is silent)
    floor_g: float = 48.2                # T3.6 48.0 + 0.2 margin; no upper limit
    lead_xz: tuple = (130.0, 21.0)       # T1.22 container under the halo, STEP frame
    lead_cap_cm3: float = 1.39
    other_parts_g: float | None = None   # None: 48.2 g minus the drawn body's foam
    other_parts_xz: tuple | None = None  # None: mid-wheelbase, z 16
    cartridge_shell_g: float = 21.15     # Part 2's car_weight_kg includes it (Appendix vi)
    thrust_z: float = 30.0
    tail_x: float = -28.5
    cartridge_out_mm: float = 13.0
    speed_mps: float = 20.0


class Car:
    """The car on a 1 mm grid with the region, rule zones and locks."""

    def __init__(self, spec: CarSpec = CarSpec(), h: float = 1.0, cache: Path | None = None):
        self.s, self.h = spec, h
        cache = cache or HERE / "cache" / f"vox_{h:g}mm.npz"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            _voxelize_step(spec, h, cache)
        d = np.load(cache)
        self.xs, self.ys, self.zs = d["xs"], d["ys"], d["zs"]
        self.body0 = d[spec.body_solid]
        self.wheels = np.zeros_like(self.body0)
        for w in spec.wheel_solids:
            self.wheels |= d[w]
        X, Y, Z = np.meshgrid(self.xs, self.ys, self.zs, indexing="ij")
        self.X, self.Y, self.Z, AY = X, Y, Z, np.abs(Y)
        s = spec
        box = ((X >= s.region_x[0]) & (X <= s.region_x[1]) & (AY <= s.region_ymax)
               & (Z - h / 2 >= s.region_z[0]) & (Z + h / 2 <= s.region_z[1]))
        dy = np.clip(AY - s.front_inner_y, 0, None)
        t792 = ((AY >= s.front_inner_y) & (X <= s.x_front_axle)
                & (X >= s.x_front_axle - s.r_wheel - (15.0 + dy / np.tan(np.radians(60)))))
        dy = np.clip(AY - s.rear_inner_y, 0, None)
        t793 = ((AY >= s.rear_inner_y) & (X >= s.x_rear_axle)
                & (X <= s.x_rear_axle + s.r_wheel + 5.0 + dy))
        halo = (X >= s.halo_x0) & (Z > s.halo_zmin)
        self.spine_zone = (AY <= s.spine_y) & (Z >= s.spine_z)
        hw = 5.0 + (X - s.cargo_x[0]) / (s.cargo_x[1] - s.cargo_x[0]) * 22.5
        self.cargo = ((X >= s.cargo_x[0]) & (X <= s.cargo_x[1]) & (AY <= hw)
                      & (Z >= s.cargo_z[0]) & (Z <= s.cargo_z[1]))
        self.forced_air = (t792 | t793 | halo) & box & ~self.spine_zone
        self.region = box & ~self.forced_air & ~self.spine_zone
        self.keep = self.body0 & ~self.region                    # never touched
        self.original_pod = self.body0 & self.region
        # signed distance of the original pod (mm, + inside) and of "nothing" (lean): field seeds
        din = ndimage.distance_transform_edt(self.body0) * h
        dout = ndimage.distance_transform_edt(~self.body0) * h
        self.sdf_original = np.where(self.body0, din, -dout).astype(np.float32)
        dcar = ndimage.distance_transform_edt(~self.cargo) * h
        self.sdf_lean = (-dcar).astype(np.float32)
        # mass bookkeeping
        self.foam0_g = self.body0.sum() * h ** 3 * 1e-3 * FOAM_G_CM3
        self.other_g = s.other_parts_g if s.other_parts_g is not None else s.floor_g - self.foam0_g
        self.other_xz = s.other_parts_xz or (0.5 * (s.x_front_axle + s.x_rear_axle), 16.0)
        # normalised coordinates for representations
        lo = np.array([s.region_x[0], 0.0, s.region_z[0]]); hi = np.array([s.region_x[1], s.region_ymax, s.region_z[1]])
        self.norm = np.stack([(X - (lo[0] + hi[0]) / 2) / ((hi[0] - lo[0]) / 2), AY / hi[1],
                              (Z - (lo[2] + hi[2]) / 2) / ((hi[2] - lo[2]) / 2)], -1).astype(np.float32)
        w = np.argwhere(self.region)
        self.rlo, self.rhi = w.min(0), w.max(0) + 1

    # ------------------------------------------------------------------ design -> body
    def finish(self, field_mm: np.ndarray) -> np.ndarray:
        """Field (mm, + = foam, full 1 mm grid; mirrored by the caller) -> body before milling."""
        f = 0.5 * (field_mm + field_mm[:, ::-1])                  # symmetric car
        return self.keep | (f > 0) & self.region | self.cargo

    def mill(self, B: np.ndarray) -> tuple[np.ndarray, dict]:
        rep = {"uncut_foam_mm3": 0.0}
        for _ in range(3):
            stuck = ~B & ~MC.reachable_air(~B, MC.TOOL_R_MM / self.h) & self.region
            n = int(stuck.sum())
            if not n:
                break
            B = B | stuck
            rep["uncut_foam_mm3"] += n * self.h ** 3
        filled = ndimage.binary_fill_holes(B)
        rep["sealed_voids_mm3"] = float(((filled & ~B) & self.region).sum() * self.h ** 3)
        B = B | (filled & self.region)
        lab, n = ndimage.label(B)
        keep = np.unique(lab[self.keep & B]); keep = keep[keep > 0]
        loose = B & ~np.isin(lab, keep)
        rep["loose_dropped_mm3"] = float(loose.sum() * self.h ** 3)
        B = B & ~loose
        B = np.where(self.region | self.cargo, B, self.body0)    # outside the region: the STEP, exactly
        B = B | self.cargo
        return B, rep

    def check(self, B: np.ndarray) -> dict:
        """Gates every evaluated car must pass (the CFD never sees a car that fails one)."""
        lab, n = ndimage.label(B)
        out = {"pieces": int(n),
               "changed_outside_region_mm3": float(((B ^ self.body0) & ~self.region & ~self.cargo).sum() * self.h ** 3),
               "foam_in_forced_air_mm3": float((B & self.forced_air).sum() * self.h ** 3),
               "cargo_inside": bool((B[self.cargo]).all()),
               "track_clearance_mm": float(self.Z[B & self.region].min() - self.h / 2) if (B & self.region).any() else None}
        out["ok"] = (n == 1 and out["changed_outside_region_mm3"] == 0 and out["foam_in_forced_air_mm3"] == 0
                     and out["cargo_inside"] and (out["track_clearance_mm"] is None or out["track_clearance_mm"] >= 1.5))
        return out

    def mass(self, B: np.ndarray) -> dict:
        s = self.s
        foam = B.sum() * self.h ** 3 * 1e-3 * FOAM_G_CM3
        lead = max(0.0, s.floor_g - self.other_g - foam)
        legal = lead <= s.lead_cap_cm3 * LEAD_G_CM3
        car = foam + self.other_g + lead
        fx, fz = self.X[B].mean(), self.Z[B].mean()
        mx = foam * fx + self.other_g * self.other_xz[0] + lead * s.lead_xz[0]
        mz = foam * fz + self.other_g * self.other_xz[1] + lead * s.lead_xz[1]
        # Part 2's race model: car weight INCLUDES the empty cartridge shell at the cartridge centre
        cx = s.tail_x - s.cartridge_out_mm + 32.5
        tot = car + s.cartridge_shell_g
        mx = (mx + s.cartridge_shell_g * cx) / tot
        mz = (mz + s.cartridge_shell_g * s.thrust_z) / tot
        return dict(foam_g=foam, lead_g=lead, car_g=car, legal=bool(legal), race_mass_g=tot,
                    com_x_car_mm=s.x_nose_mm - mx, com_z_mm=mz)

    def build(self, field_mm: np.ndarray) -> dict:
        B, rep = self.mill(self.finish(field_mm))
        chk = self.check(B)
        return dict(body=B, mill=rep, check=chk, mass=self.mass(B))

    # ------------------------------------------------------------------ export for CFD
    def export_car_folder(self, B: np.ndarray, out: Path, label: str = "") -> Path:
        """Folder Part 2's stopwatch / any OpenFOAM or SimScale run can time:
        car_half.stl (solid `car`, m, car frame, y >= 0, closed at y = 0), wheelF/wheelR.stl,
        assembly.json (rotating wheels), mass_report.json, body_full.stl (whole body, for SimScale
        and the CNC)."""
        import trimesh
        out = Path(out); out.mkdir(parents=True, exist_ok=True)
        half = self._surface(B, half=True)
        half.export(out / "car_half_raw.stl")
        _write_named_ascii(half, out / "car_half.stl", "car")
        _write_named_ascii(self._surface(B, half=False), out / "body_full.stl", "car")
        s = self.s
        omega = -s.speed_mps / (s.r_wheel / 1e3)
        surfaces = []
        for name, xa in (("wheelF", s.x_front_axle), ("wheelR", s.x_rear_axle)):
            m = self._surface(self.wheels & (np.abs(self.X - xa) < s.r_wheel + 3), half=True, smooth=False)
            m.apply_translation([0, 0, -WHEEL_SINK_MM / 1e3])     # Part 4: wheels sunk into the road
            _write_named_ascii(m, out / f"{name}.stl", name)
            yc = (s.front_inner_y if name == "wheelF" else s.rear_inner_y) + 8.6
            surfaces.append({"name": name, "stl": f"{name}.stl", "rotating": {
                "origin": [(s.x_nose_mm - xa) / 1e3, yc / 1e3, (s.r_wheel - WHEEL_SINK_MM) / 1e3], "axis": [0, 1, 0], "omega": omega}})
        (out / "assembly.json").write_text(json.dumps({"extra_surfaces": surfaces, "label": label}, indent=1))
        m = self.mass(B)
        (out / "mass_report.json").write_text(json.dumps({
            "car_weight_kg": m["race_mass_g"] / 1e3, "com_mm": [m["com_x_car_mm"], 0.0, m["com_z_mm"]],
            "foam_g": m["foam_g"], "lead_g": m["lead_g"], "car_without_cartridge_g": m["car_g"],
            "note": "sidepod_opt: exact foam from the milled 1 mm body; other parts ASSUMED (see CarSpec)"}, indent=1))
        return out

    def _surface(self, M, half=True, smooth=True):
        import trimesh
        from skimage import measure
        j0 = np.searchsorted(self.ys, 0.0)
        A = M[:, j0:] if half else M
        ys = self.ys[j0:] if half else self.ys
        P = np.pad(A.astype(np.float32), 2)
        if half:
            P[:, :2, :] = 0.0                                     # closed at the symmetry plane
        if smooth:
            P = ndimage.gaussian_filter(P, 0.6)
        v, f, _n, _ = measure.marching_cubes(P, 0.5)
        h = self.h
        x = self.xs[0] + (v[:, 0] - 2) * h
        y = ys[0] + (v[:, 1] - 2) * h
        z = self.zs[0] + (v[:, 2] - 2) * h
        if half:
            y = np.where(y < ys[0] - h / 2, 0.0, y)               # the closing face sits on y = 0
            y = np.maximum(y, 0.0)
        verts = np.c_[(self.s.x_nose_mm - x) / 1e3, y / 1e3, np.maximum(z, 0.0) / 1e3]
        m = trimesh.Trimesh(verts, f[:, ::-1], process=True)       # x flipped: keep normals outward
        m.merge_vertices(); m.update_faces(m.nondegenerate_faces()); m.remove_unreferenced_vertices()
        if smooth:
            trimesh.smoothing.filter_taubin(m, iterations=6)
            if half:
                v = m.vertices.copy(); v[:, 1] = np.where(v[:, 1] < 2e-4, np.maximum(v[:, 1], 0.0), v[:, 1])
                v[v[:, 1] < 5e-5, 1] = 0.0; m.vertices = v
        trimesh.repair.fix_normals(m)
        return m


def _write_named_ascii(mesh, path: Path, name: str):
    import trimesh
    txt = trimesh.exchange.stl.export_stl_ascii(mesh)
    lines = txt.splitlines()
    lines[0] = f"solid {name}"; lines[-1] = f"endsolid {name}"
    path.write_text("\n".join(lines) + "\n")


def _voxelize_step(spec: CarSpec, h: float, out: Path):
    """STEP -> tessellate -> 3-axis ray-parity voxels (survives small seams)."""
    sys.path.append(str(REPO / "research/sidepod_region"))
    import step_vox
    step_vox.voxelize(spec.step, h, out)
