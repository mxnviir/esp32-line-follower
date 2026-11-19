#!/bin/bash
cd "$(dirname "$0")"
export NUMBA_NUM_THREADS=2
python topo_run.py 1 30 >> results/queue2.log 2>&1
for m in random cma bo sail spsa neat; do python run_one.py $m 2 30 >> results/queue2.log 2>&1; done
