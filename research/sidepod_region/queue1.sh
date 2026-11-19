#!/bin/bash
cd "$(dirname "$0")"
export NUMBA_NUM_THREADS=2
python refs.py > results/refs.txt 2>&1
for s in 1 2; do for m in random cma bo sail; do python run_one.py $m $s 30 >> results/queue1.log 2>&1; done; done
