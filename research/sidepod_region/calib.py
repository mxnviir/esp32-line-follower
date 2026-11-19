"""Original car from rest: convergence, cost, and two 'frozen states' (A at 6000, B at 7000
steps) to measure how much a result depends on the start state (the noise)."""
import numpy as np, time, json
from region import Car
from tunnel import CarTunnel
import lbm3d as L
c = Car(); T = CarTunnel(c)
t = time.time()
r = T.measure(c.original, 5000, 0)
np.save("results/state_A.npy", r["state"]); h1 = r["hist"]
r2 = T.measure(c.original, 1000, 0, warm=r["state"])
np.save("results/state_B.npy", r2["state"])
dt = time.time() - t
h = np.vstack([h1, r2["hist"]]); d = h[:, 0] + h[:, 3]; l = h[:, 2] + h[:, 5]
np.save("results/base_hist.npy", h)
f = r2["state"].astype(float); rho = f.sum(0)
print("s/step", dt / 6000, "cells", np.prod(T.shape), "rho range fluid", rho[f.sum(0) > 0].min(), rho.max())
for k in range(0, len(d), 4): print(50 * k, round(float(d[k]), 4), round(float(h[k, 0]), 4), round(float(h[k, 3]), 4), round(float(l[k]), 3))
