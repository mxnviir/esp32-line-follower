#!/bin/bash
cd "$(dirname "$0")/.."
for v in "$@"; do topo/run_topo.sh topo/$v 4; echo "done $v $(date -u +%T)"; done
echo OPT_QUEUE_DONE
