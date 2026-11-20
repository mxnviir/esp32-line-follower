#!/usr/bin/env python
"""DAFoam (v5, discrete adjoint): half-car drag and its exact derivative with respect to every surface
point of the `car` patch. Run inside the DAFoam image, in the case folder made by make_case.py:

    mpirun -np 4 python runScript.py            # -> dafoam_sens.npz (Xs, dD_dXs, D_N, ...)

Drag = the force on car + wheelF + wheelR along +x, in N for the half car (DASimpleFoam's force is
kinematic, so scale = rho). The design surface is `car` only (the sidepod lives there).
No FFD: the derivative is taken with respect to the surface coordinates themselves (mesh.x_aero0 ->
cruise.x_aero), so any shape change can be scored afterwards as  dD = sum_i dD/dXs_i . dX_i .
Boundary conditions come from the 0/ files as written (useWallFunction is NOT set, so DAFoam keeps
the pipeline's Spalding wall functions, rolling road and rotating wheels).
"""
import json
import os
import time

import numpy as np
import openmdao.api as om
from mphys.core import Multipoint
from mphys.scenarios import ScenarioAerodynamic
from mpi4py import MPI

from dafoam.mphys import DAFoamBuilder

gcomm = MPI.COMM_WORLD
U0, RHO = 20.0, 1.225
K0, OMEGA0 = 0.015, 202.7027
GMRES_TOL = float(os.environ.get("DAF_GMRES_TOL", "1e-6"))
GMRES_IT = int(os.environ.get("DAF_GMRES_ITERS", "2000"))
FILL = int(os.environ.get("DAF_PC_FILL", "1"))

daOptions = {
    "solverName": "DASimpleFoam",
    "designSurfaces": ["car"],
    # the pipeline's steady solves stall near a 1e-3 residual (a wake that never quite settles): run the
    # fixed number of iterations in controlDict and never flag the primal as failed for its residual
    "primalMinResTol": 1.0e-12,
    "primalMinResTolDiff": 1.0e12,
    "function": {
        "D": {
            "type": "force",
            "source": "patchToFace",
            "patches": ["car", "wheelF", "wheelR"],
            "directionMode": "fixedDirection",
            "direction": [1.0, 0.0, 0.0],
            "scale": RHO,
        },
    },
    "normalizeStates": {"U": U0, "p": U0 * U0 / 2.0, "k": K0, "omega": OMEGA0, "phi": 1.0},
    "adjEqnOption": {"gmresRelTol": GMRES_TOL, "gmresAbsTol": 1.0e-16, "gmresMaxIters": GMRES_IT,
                     "gmresRestart": GMRES_IT, "pcFillLevel": FILL, "jacMatReOrdering": "rcm"},
    "adjPCLag": 1,
    "checkMeshThreshold": {"maxAspectRatio": 1000.0, "maxNonOrth": 70.0, "maxSkewness": 6.0,
                           "maxIncorrectlyOrientedFaces": 0},
    "inputInfo": {"aero_vol_coords": {"type": "volCoord", "components": ["solver", "function"]}},
}

meshOptions = {
    "gridFile": os.getcwd(),
    "fileType": "OpenFOAM",
    "symmetryPlanes": [[[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]]],   # the half-car plane y = 0
}


class Top(Multipoint):
    def setup(self):
        b = DAFoamBuilder(daOptions, meshOptions, scenario="aerodynamic")
        b.initialize(self.comm)
        self.add_subsystem("mesh", b.get_mesh_coordinate_subsystem())
        self.mphys_add_scenario("cruise", ScenarioAerodynamic(aero_builder=b))
        self.connect("mesh.x_aero0", "cruise.x_aero")


def main():
    t0 = time.time()
    prob = om.Problem()
    prob.model = Top()
    prob.setup(mode="rev")
    prob.run_model()
    D = float(prob.get_val("cruise.aero_post.D")[0])
    t1 = time.time()
    if gcomm.rank == 0:
        print(f"DAFOAM primal D_half = {D:.6f} N  ({t1 - t0:.0f} s)", flush=True)
    tot = prob.compute_totals(of=["cruise.aero_post.D"], wrt=["mesh.x_aero0"], get_remote=True)
    g = np.asarray(tot[("cruise.aero_post.D", "mesh.x_aero0")]).ravel()
    t2 = time.time()
    DASolver = prob.model.cruise.coupling.solver.DASolver
    Xs = np.asarray(DASolver.getSurfaceCoordinates(DASolver.designSurfacesGroup)).ravel()
    off = gcomm.exscan(len(Xs)) or 0
    local = g[off:off + len(Xs)]
    allX = gcomm.gather(Xs, root=0)
    allG = gcomm.gather(local, root=0)
    if gcomm.rank == 0:
        X = np.concatenate(allX).reshape(-1, 3)
        G = np.concatenate(allG).reshape(-1, 3)
        np.savez("dafoam_sens.npz", Xs=X, dD_dXs=G, D_N=D, primal_s=t1 - t0, adjoint_s=t2 - t1,
                 nproc=gcomm.size, gmres_tol=GMRES_TOL)
        json.dump({"D_half_N": D, "n_surface_points": int(len(X)), "primal_s": t1 - t0, "adjoint_s": t2 - t1,
                   "nproc": gcomm.size, "sum_dD_dXs": G.sum(0).tolist()}, open("dafoam_sens.json", "w"), indent=1)
        print(f"DAFOAM adjoint done: {len(X)} surface points, {t2 - t1:.0f} s", flush=True)


if __name__ == "__main__":
    main()
