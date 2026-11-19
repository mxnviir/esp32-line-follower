"""Ray-parity voxelization of the tessellated STEP solids at 1 mm, cast along x, y and z;
a cell is solid when at least 2 of the 3 directions say so (survives small seams in a
non-watertight tessellation). Writes cad/vox1mm.npz."""
import json, numpy as np, trimesh
from numba import njit
from pathlib import Path
HERE = Path(__file__).resolve().parent
H = 1.0
XS = np.arange(-30.0, 231.0, H) + H / 2
YS = np.arange(-40.0, 40.0, H) + H / 2
ZS = np.arange(0.0, 50.0, H) + H / 2


@njit(cache=True)
def parity(tri, A, B, C, nA, nB, nC):
    """tri (n,3,3) in (a,b,c) axis order; rays along c through cell centres (A[i], B[j])."""
    hits = [[0.0 for _ in range(0)] for _ in range(nA * nB)]
    for t in range(tri.shape[0]):
        p0, p1, p2 = tri[t, 0], tri[t, 1], tri[t, 2]
        amin = min(p0[0], p1[0], p2[0]); amax = max(p0[0], p1[0], p2[0])
        bmin = min(p0[1], p1[1], p2[1]); bmax = max(p0[1], p1[1], p2[1])
        i0 = max(0, int(np.ceil((amin - A[0]) / (A[1] - A[0])))); i1 = min(nA - 1, int(np.floor((amax - A[0]) / (A[1] - A[0]))))
        j0 = max(0, int(np.ceil((bmin - B[0]) / (B[1] - B[0])))); j1 = min(nB - 1, int(np.floor((bmax - B[0]) / (B[1] - B[0]))))
        d = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
        if abs(d) < 1e-12:
            continue
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                a = A[i] + 1e-7; b = B[j] + 1.3e-7
                u = ((p1[0] - a) * (p2[1] - b) - (p2[0] - a) * (p1[1] - b)) / d
                v = ((p2[0] - a) * (p0[1] - b) - (p0[0] - a) * (p2[1] - b)) / d
                w = 1 - u - v
                if u < 0 or v < 0 or w < 0:
                    continue
                hits[i * nB + j].append(u * p0[2] + v * p1[2] + w * p2[2])
    out = np.zeros((nA, nB, nC), np.bool_)
    for i in range(nA):
        for j in range(nB):
            h = np.array(hits[i * nB + j]); h.sort()
            # merge near-duplicates (ray through a shared edge)
            m = []
            for k in range(h.size):
                if len(m) == 0 or h[k] - m[-1] > 1e-5:
                    m.append(h[k])
            for k in range(0, len(m) - 1, 2):
                for c in range(nC):
                    if C[c] > m[k] and C[c] < m[k + 1]:
                        out[i, j, c] = True
    return out


def vox(mesh):
    T = mesh.triangles.astype(np.float64)
    g = {}
    g["z"] = parity(T[:, :, [0, 1, 2]].copy(), XS, YS, ZS, len(XS), len(YS), len(ZS))
    g["y"] = parity(T[:, :, [0, 2, 1]].copy(), XS, ZS, YS, len(XS), len(ZS), len(YS)).transpose(0, 2, 1)
    g["x"] = parity(T[:, :, [1, 2, 0]].copy(), YS, ZS, XS, len(YS), len(ZS), len(XS)).transpose(2, 0, 1)
    votes = g["x"].astype(int) + g["y"] + g["z"]
    return votes >= 2, {k: int(v.sum()) for k, v in g.items()}


if __name__ == "__main__":
    S = json.loads((HERE / "cad/summary.json").read_text())
    res = {}
    for n in S:
        m = trimesh.load(HERE / f"cad/{n}.stl")
        res[n], per = vox(m)
        print(n, "vox", int(res[n].sum()), "per-axis", per, "CAD", S[n]["volume_mm3"], flush=True)
    np.savez_compressed(HERE / "cad/vox1mm.npz", xs=XS, ys=YS, zs=ZS, **res)
