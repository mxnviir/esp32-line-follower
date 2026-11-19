#!/bin/bash
cd "$(dirname "$0")"
export NUMBA_NUM_THREADS=2
python refs.py skip-original >> results/refs.txt 2>&1
for m in random cma bo sail spsa neat; do python run_one.py $m 1 30 >> results/queue1.log 2>&1; done
