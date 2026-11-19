#!/bin/bash
# One 2-core lane of the adjoint gate. Waits for the solve it inherits (pid $1), then takes bump
# names one at a time from gate/queue.txt (edit that file to reorder or replace what is left).
# The last lane to finish runs the judge. Every result is committed and pushed as it lands.
cd "$(dirname "$0")"
REPO=$(git rev-parse --show-toplevel)
commit() { flock gate/git.lock ./gate_commit.sh "$1" || true; }
pop() { flock gate/queue.lock bash -c 'k=$(head -1 gate/queue.txt); [ -n "$k" ] && sed -i 1d gate/queue.txt; echo $k'; }
while kill -0 "$1" 2>/dev/null; do sleep 30; done
commit "bump ($2)"
while k=$(pop) && [ -n "$k" ]; do
  echo "$(date -u) start $k" >> gate/worker_$$.log
  ./gate_run.sh b_$k bump $k 2; commit "bump $k"
done
touch gate/worker_done_$$
if [ "$(ls gate/worker_done_* | wc -l)" -ge 2 ]; then
  python -W ignore gate.py judge > gate/job_judge.log 2>&1; commit "judge: adjoint vs measured"
  echo GATE_DONE $(date -u) >> gate/job_judge.log
fi
