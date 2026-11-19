# Literature for this exact problem

Searched 2026-11-19. The problem: a small CO2 car under STEM Racing rules, with three layout
numbers (halo position, rear overhang, wheelbase), and everything else created freely: an
organic foam body milled 3-axis from one block, plus ABS-printed wheel supports with built-in
axles, a nose cone and wings, joined flush into the foam. Scored on race time.

**Bottom line: no published work solves this whole problem.** Every piece exists separately,
and the gaps are exactly where this car is hardest.

## 1. F1 in Schools / STEM Racing cars

What exists is manual iteration with CFD and wind tunnels, not automated optimisation.

- A 2024 study combined CFD with wind-tunnel testing and cut drag by 9.89 % through hand-made
  changes aimed at separation.
  [JAEDS 2024](https://jaeds.uitm.edu.my/index.php/jaeds/article/view/77)
- Sidepod and diffuser modifications studied by hand in STAR-CCM+, trading drag against
  downforce. [ResearchGate](https://www.researchgate.net/publication/326982520_Study_on_the_modification_effect_of_side_pot_and_diffuser_to_the_aerodynamics_of_the_F1_IN_SCHOOLS_car)
- Rear-end variants spread Cd from 0.122 to 0.164.
  [Modern Applied Science 2021](https://www.researchgate.net/publication/350519387_Improving_Aerodynamic_Efficiency_and_Decreasing_Drag_Coefficient_of_an_F1_in_Schools_Race_Car/fulltext/60648457299bf173678112e2/Improving-Aerodynamic-Efficiency-and-Decreasing-Drag-Coefficient-of-an-F1-in-Schools-Race-Car.pdf)
- A worked example notes the remaining scope is around the wheels and the canister gap.
  [Symscape](https://www.symscape.com/examples/rans/cfd-f1-in-schools)

**For us:** nothing to copy for method. It does confirm that wheels dominate, and that sidepods
and diffusers are a known lever.

## 2. Adjoint optimisation of car bodies (free-form surfaces)

- **Works on cars, but with limits.** Steady adjoint on the DrivAer model gave notable drag cuts
  within four cycles, but was unstable on finer meshes and in separated, rotational flow.
  [Chalmers](https://odr.chalmers.se/items/e625457f-41b4-481d-baaf-8f31e7097bbe)
- **Steady adjoint on time-averaged flow** has been reported to work for highly turbulent
  vehicle flows.
  [Adjoint lattice Boltzmann, AIAA J.](https://arc.aiaa.org/doi/10.2514/1.J057955)
- **Commercial tools aren't all ready.** One project found Fluent's adjoint not ready for
  external aerodynamics.
  [Chalmers](https://publications.lib.chalmers.se/records/fulltext/175630/175630.pdf)
- Review of adjoint methods for car aerodynamics:
  [ResearchGate](https://www.researchgate.net/publication/274365416_Adjoint_methods_for_car_aerodynamics)

**For us:** adjoint *shape* optimisation is proven for car bodies over a few cycles. Our
rear-wheel wake is separated and bistable, which is exactly where it is reported unstable. Use
it for polish, with a gate.

## 3. Topology optimisation in turbulent flow (can invent new forms)

- Density-based topology optimisation with Spalart–Allmaras turbulence exists.
  [Yoon](https://www.researchgate.net/publication/294111445_Topology_optimization_for_turbulent_flow_with_Spalart-Allmaras_model)
- **It breaks down as Reynolds number rises:** the adjoint turbulence model loses stability.
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0045782520307362)
- OpenFOAM continuous-adjoint topology optimisation in turbulent flow exists, but only for
  internal and heat-transfer devices.
  [Springer](https://link.springer.com/article/10.1007/s00158-022-03311-z),
  [DTU](https://backend.orbit.dtu.dk/ws/files/163013736/Density_Based_TopologyOptimization_Of_TurbulentFlow_HeatTransferSystems.pdf)
- Industrial continuous-adjoint applications:
  [Papoutsis-Kiachagias et al.](https://www.researchgate.net/publication/273705112_Continuous_Adjoint_Methods_for_Turbulent_Flows_Applied_to_Shape_and_Topology_Optimization_Industrial_Applications)
- **No 3D external bluff-body drag result with k-ω SST was found.**

**For us:** using topology optimisation to invent sidepods or tunnels in turbulent external flow
is research-grade. It is possible on OpenFOAM, but expect to be first, with stability work.

## 4. Layout numbers outside, free shape inside (bilevel)

- Closest match: a nested method with a Bayesian infill optimiser outside and a gradient
  optimiser inside, variables split by whether adjoint derivatives exist. It also measures how
  much performance is lost by freezing the layout.
  [Wingbox, J. Aircraft](https://arc.aiaa.org/doi/10.2514/1.C036315)
- A bilevel model-based design method.
  [arXiv 2607.29161](https://arxiv.org/pdf/2607.29161)

**For us:** the structure "Bayesian optimisation over the 3 layout numbers, adjoint for the
geometry inside" has a precedent, but in structures, not car aero.

## 5. Shape and structure together (supports, wing mounts)

- Coupled aerodynamic shape and structural topology optimisation gave **18 % less drag than
  doing them one after the other**.
  [Springer](https://link.springer.com/article/10.1007/s00158-022-03234-9)
- Simultaneous shape and topology optimisation of wings with a strut. Most drag came between
  the root and the strut mount, but the strut's own drag was left out.
  [arXiv 2209.09330](https://arxiv.org/pdf/2209.09330)
- Aerostructural wing-box topology optimisation.
  [Computers & Structures](https://www.sciencedirect.com/science/article/abs/pii/S0045794913003398),
  [NASA](https://www.nas.nasa.gov/assets/nas/pdf/ams/2021/AMS_20211209_Ranjan.pdf)

**For us:** growing supports structurally and then fixing their aero afterwards leaves real
performance behind. Coupling matters. Nobody has published minimum-drag support mounts.

## 6. Manufacturing constraints inside the optimisation

- **3-axis milling inside level-set topology optimisation** (approach directions, tool and
  holder geometry). This fits the foam body directly.
  [Morris et al., arXiv 2002.10246](https://arxiv.org/pdf/2002.10246),
  [SMO 2024](https://link.springer.com/article/10.1007/s00158-024-03928-2),
  [KOBV thesis](https://opus4.kobv.de/opus4-w-hs/frontdoor/index/index/docId/4702),
  [NSF PAR](https://par.nsf.gov/servlets/purl/10337081)
- **Multi-material parts with optimised joint interfaces and print orientation.** This fits the
  ABS-into-foam joints and FDM layer weakness.
  [Anisotropic multicomponent TO, arXiv 1911.10393](https://arxiv.org/html/1911.10393v1),
  [interlocking joints](https://www.sciencedirect.com/science/article/pii/S2214860426002186),
  [joint stiffness](https://www.sciencedirect.com/science/article/abs/pii/S0168874X21001190),
  [dimensional and assembly constraints](https://www.sciencedirect.com/science/article/abs/pii/S0045782523001512)

**For us:** the milling and joint constraints can be built into the optimiser's step itself,
not checked afterwards as we do now. These papers are structural only; none has airflow.

## 7. Generative AI for car shapes

- A triplane VAE whose latent space knows drag, searched and checked with CFD.
  [TripOptimizer](https://arxiv.org/pdf/2509.12224)
- An autoencoder with a drag head, optimised in latent space.
  [Nature Comms Eng.](https://www.nature.com/articles/s44172-024-00322-0)
- Survey of generative methods in automotive aero.
  [JCDE](https://academic.oup.com/jcde/article/13/1/538/8408453)
- **Caution:** an unreviewed project found its optimiser "hacked" the drag model, and real CFD
  drag went *up*.
  [GitHub](https://github.com/AdiArtifice/Generative-Design-Low-Drag-Car-Bodies)
- Inverse design on DrivAerNet++.
  [arXiv 2602.03582](https://ar5iv.labs.arxiv.org/html/2602.03582)

**For us:** these need thousands of training cars and produce passenger-car-like shapes. Not a
fit for one STEM car at our budget.

## What this means for the plan

1. **Layout:** Bayesian optimisation over the 3 numbers has precedent (§4).
2. **Supports:** coupled aero and structure topology optimisation (§5), with print orientation
   and joints built in (§6), not structure first and aero after.
3. **Foam body:** adjoint level-set shape optimisation with the 3-axis milling constraint
   inside the step (§2 + §6). Topology changes (tunnels, splits) come from several starting
   shapes and from a topology-optimisation attempt (§3), which is research-grade.
4. **Gates:** the adjoint must pass a finite-difference check, and every result must be
   confirmed by plain CFD (§2's instability in separated flow).
5. **Wings:** parametric, as planned. Their Reynolds number (~20,000) needs a transition model
   or a transient check.
