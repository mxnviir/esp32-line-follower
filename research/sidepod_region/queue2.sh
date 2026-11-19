#!/bin/bash
cd "$(dirname "$0")"
while [ ! -f results/base.json ]; do sleep 20; done
export NUMBA_NUM_THREADS=2
for s in 1 2; do
  TOPO_V=2 python topo_run.py $s 30 >> results/queue2.log 2>&1
  for m in spsa neat; do python run_one.py $m $s 30 >> results/queue2.log 2>&1; done
done
