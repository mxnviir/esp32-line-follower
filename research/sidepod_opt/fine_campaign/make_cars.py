"""Rebuild every car of the fine-mesh campaign from code, on any machine (the run folders are not in git).

    python fine_campaign/make_cars.py [out_dir]      (default: runs/fine_cars)  -> <out>/<tag>/car
    python fine_campaign/make_cars.py --check        rebuild into a temp dir, compare with runs/ here

Every recipe is the one used on 2026-11-20/21 (ROUTES.md): the shape-loop seeds, the blends, the window
cut, design 8 of run cloud_original (its field is in git), and the "_p05 / _m05" copies shifted by
+/-0.05 mm (a physical change < 0.01 mN by the adjoint) so each gets its own mesh: the mesh-to-mesh
scatter of every design is measured, not assumed.
"""
import sys
from pathlib import Path
import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
SP = HERE.parent
sys.path.insert(0, str(SP)); sys.path.insert(0, str(SP.parents[1] / "part2-simulation"))
import shape_loop as SL  # noqa: E402

FIELD_IT8 = SP / "runs" / "cloud_original" / "it_008" / "field.npz"
# tag -> existing local folder it must match (for --check)
LOCAL = {"team": "runs/cloud_original/it_000/car", "nopod": "runs/cloud_lean/it_000/car", "groove": "runs/concepts/channel/car",
         "blend50": "runs/concepts/blend50/car", "blend75": "runs/concepts/blend75/car", "win3": "runs/concepts/win3/car",
         "win5": "runs/concepts/win5/car", "adjoint8": "runs/cloud_original/it_008/car", "team_p05": "runs/concepts/seed_p05/car",
         "team_m05": "runs/concepts/seed_m05/car", "groove_p05": "runs/concepts/channel_p05/car", "adjoint8_p05": "runs/concepts/it8_p05/car"}


def windows(car, f0, xs_list, wall=3.0):
    """Vertical through-windows between the cargo cover + wall and the pod's outer skin - wall (as built 2026-11-21)."""
    s = car.s
    X, AY = car.X, np.abs(car.Y)
    hw = 5.0 + (X - s.cargo_x[0]) / (s.cargo_x[1] - s.cargo_x[0]) * 22.5
    B0 = car.finish(f0) & car.region
    ymax_pod = np.where(B0.any(2), AY[:, :, 0], 0).max(1)
    cut = np.zeros(f0.shape, bool)
    yin = np.where(X < s.cargo_x[0], s.spine_y + wall, np.maximum(hw, s.spine_y) + wall)
    yout = ymax_pod[:, None, None] - wall
    for x0, x1 in xs_list:
        cut |= (X >= x0) & (X <= x1) & (AY >= yin) & (AY <= yout)
    d = ndimage.distance_transform_edt(~cut) * car.h
    return np.minimum(f0, d - 0.5 * car.h - 1e-6 + np.where(cut, -50.0, 0.0))


def fields(car):
    S = SL.seeds(car)
    so, sl = car.sdf_original.astype(float), car.sdf_lean.astype(float)
    team_rules = SL.build_design(car, S["original"])["f_rules"]
    f8 = np.load(FIELD_IT8)["f"]
    out = {
        "team": S["original"], "nopod": S["lean"], "groove": S["channel"],
        "blend50": 0.5 * so + 0.5 * sl, "blend75": 0.75 * so + 0.25 * sl,
        "win3": windows(car, so, [(60, 72), (80, 92), (100, 112)]),
        "win5": windows(car, so, [(55, 63), (67, 75), (79, 87), (91, 99), (103, 111)]),
        "adjoint8": f8,
        # repeat-mesh copies (same recipes as runs/concepts/seed_p05 etc.)
        "team_p05": team_rules + 0.05 * car.region, "team_m05": team_rules - 0.05 * car.region,
        "adjoint8_p05": f8 + 0.05, "adjoint8_m05": f8 - 0.05,
    }
    for k in ("groove", "nopod", "win3", "blend50", "blend75"):
        base = SL.build_design(car, out[k])["f_rules"]
        out[f"{k}_p05"] = base + 0.05 * car.region
    return out


def main():
    check = "--check" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else SP / "runs" / "fine_cars"
    if check:
        import tempfile
        out = Path(tempfile.mkdtemp())
    car = SL.load_car()
    for tag, f in fields(car).items():
        b = SL.build_design(car, np.asarray(f, float))
        if not b["check"]["ok"]:
            print(tag, "FAILED the build check", b["check"], flush=True)
            continue
        folder = SL.export_design(car, b, out / tag, tag)
        line = f"{tag:14s} pod {(b['voxels'] & car.region).sum() * 1e-3:5.1f} cm3  mass {b['mass']['race_mass_g']:.2f} g  lead {b['mass']['lead_g']:.2f} g  volume {b['mesh'].volume:.1f} mm3"
        if check and tag in LOCAL and (SP / LOCAL[tag] / "car_half.stl").exists():
            import trimesh
            a = trimesh.load(folder / "car_half.stl"); r = trimesh.load(SP / LOCAL[tag] / "car_half.stl")
            line += f"  | vs {LOCAL[tag]}: dV {a.volume - r.volume:+.3f} mm3, verts {len(a.vertices)} vs {len(r.vertices)}"
        print(line, flush=True)


if __name__ == "__main__":
    main()
