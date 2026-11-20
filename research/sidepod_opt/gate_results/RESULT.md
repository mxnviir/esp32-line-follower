# Adjoint accuracy gate: result (2026-11-20, finished 03:51 UTC)

**Verdict: the ESI adjoint does not predict drag changes on this car. Do not take adjoint steps.**

Half-car drag, mN. Noise: per-run stderr about 0.2 mN. The null bump (0.02 mm) measured -0.05 mN.

## Independent tests

There are three, not 8 rows: +/- twins and the 0.75/1.5 mm amplitudes share one shape.

| Test | Measured half-diff | Adjoint (first) | Adjoint (matched mesh) | Measured / stderr |
|---|---|---|---|---|
| Along the adjoint gradient, ±1.5 mm | **-1.00 ± 0.29** | +1.68 | +1.52 | 3.4 σ, opposite sign |
| pod_front_low, ±1 mm | **-1.13 ± 0.17** | +0.09 | -0.01 | 6.8 σ; predicted about 0 |
| pod_rear, ±1 mm | **-1.27 ± 0.18** | +0.00 | -0.10 | 7.0 σ; predicted 12x too small |

- `pod_front_low` and `pod_rear` stderr: about 0.2 mN was assumed for the + run because its forces were not saved.
- `grad_p075` measured -0.53 ± 0.20 against a prediction of +0.76. That is only 2.7 σ from zero and is not linear with the 1.5 mm step (-0.41).
- Flipping `OUTWARD_SIGN` does not save it. The gradient row would then match, but the site pairs still miss by more than 10x under either sign.
- Over all 8 rows: first map r = -0.54, signs 0/8; matched map r = -0.47, signs 4/8. Part 3's marks (r ≥ 0.9, signs ≥ 80 %) fail by a wide margin.

## Checks that it is not a setup error

- **Objective patches** = `(car wheelF wheelR)`. That is the same set the `forces` function object (D20) integrates.
- **Adjoint converged:** Ua initial residual 2.3e-6, pa 1.0e-5 at the end.
- **The two adjoints agree with each other** (r = 0.82 per vertex): repeatable, but wrong.
- **Correction (found while setting up DAFoam):** the "matched" adjoint was matched in wall layers and primal length only. Its mesh had **375,068 cells**; state A's mesh, the one the bumps were measured on, has **519,620** (`checkMesh`). ESI's adjoint path meshes the car itself and leaves out part of Part 2's refinement. Neither ESI adjoint solved the flow the bumps were measured in. That supports, but does not prove, the verdict below. The DAFoam test runs on state A's own mesh and flow.
- **Remaining mismatch (open):** the adjoint solver's own primal gives D20 = 187.5 mN against the bumps' state A of 182.9 mN (+2.5 %).
  - The convection and gradient schemes are the same. The laplacian/snGrad limiter differs: `limited 0.333` in the adjoint vs `limited corrected 0.5`.
  - These are the adjoint-stability settings in `part2-simulation/openfoam_adjoint.py`. The mismatch is real, but it is a 2.5 % change in the base flow. It is unlikely to turn a -1.2 mN measured response into a predicted 0.

## Physics found

Growing the sidepod by 1 mm at the front-low (X≈134 mm) and rear (X≈69 mm) sites each **reduce** drag by about 1.1–1.3 mN per half car. Denting them raises it. Use these as the start points for a measured-map / direct CFD search, per Part 3.

## Next (codespace)

Do ± pairs at the remaining sidepod sites, both halves on the same machine:

    GATE_JOBS="pod_front: pod_front_m:pod_front:-1 pod_rear_low: pod_rear_low_m:pod_rear_low:-1 pod_rear_top: pod_rear_top_m:pod_rear_top:-1" ./codespace_gate.sh start
