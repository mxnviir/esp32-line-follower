#!/bin/bash
cd "$(dirname "$0")"
while pgrep -f queue1.sh > /dev/null; do sleep 30; done
export NUMBA_NUM_THREADS=2
TOPO_V=2 python topo_run.py 1 30 >> results/queue3.log 2>&1
