#!/bin/bash
# Copies each live run's force histories (and its pid's bump name) every 60 s into
# gate_results/forces/<run>/, so they survive cmd_bump deleting the run folder.
RUNS=../../part2-simulation/cfd_case_template/runs
while true; do
  for d in $RUNS/run_*; do
    [ -d "$d/postProcessing" ] || continue
    n=$(basename "$d"); o=gate_results/forces/$n; mkdir -p "$o"
    pid=${n#run_}; pid=${pid%%_*}
    tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -o 'gate.py [a-z]* [a-z_0-9]*' > "$o/job.txt"
    for f in forces forces_car; do cp -f "$d/postProcessing/$f/0/force.dat" "$o/$f.dat" 2>/dev/null; done
  done
  sleep 60
done
