#!/bin/bash
# Run (or resume) shape_loop.py on THIS machine, one iteration at a time, committing after each.
# Safe to start again after a restart: swap back on, the loop resumes from runs/<name>/state.json.
#   bash research/sidepod_opt/run_loop_here.sh <name> <seed> [max_iters]
# Stop it cleanly: touch research/sidepod_opt/runs/<name>/STOP
# Log: research/sidepod_opt/gate/loop_<name>.log ("LOOP_END <reason>" when it ends)
cd "$(dirname "$0")"                                   # research/sidepod_opt
NAME=${1:?name}; SEED=${2:?seed}; MAX=${3:-40}
RUN=runs/$NAME; LOG=gate/loop_$NAME.log
mkdir -p gate runs
exec >> "$LOG" 2>&1
pgrep -f "shape_loop.py run $RUN" >/dev/null && { echo "already running"; exit 0; }
swapon --show | grep -q swapfile || swapon /swapfile 2>/dev/null || true
docker info >/dev/null 2>&1 || { (dockerd > gate/dockerd.log 2>&1 &); sleep 10; }
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export PATH=/opt/py/bin:$PATH CFD_DIV_U="bounded Gauss upwind" OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
       OMPI_MCA_rmaps_base_oversubscribe=1
REPO=$(git rev-parse --show-toplevel); BR=$(git rev-parse --abbrev-ref HEAD)
commit() {
  ( cd "$REPO"
    d=research/sidepod_opt/$RUN
    for f in $d/log.jsonl $d/config.json $d/state.json $d/it_*/cfd.json; do [ -e "$f" ] && git add -f "$f"; done
    [ -n "$1" ] && for f in $d/best_car $d/current.npz; do [ -e "$f" ] && git add -f "$f"; done
    git commit -q -m "shape loop ($NAME): ${1:-iteration}

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoaxAjmcpDSsbf6r9F3" || return 0
    for i in 1 2 3 4; do git pull -q --no-rebase --no-edit origin "$BR" 2>/dev/null; git push -q origin "$BR" 2>/dev/null && break; sleep $((2 ** i)); done )
}
echo "START $(date -u) uptime_min=$(awk '{print int($1/60)}' /proc/uptime)"
[ -f $RUN/state.json ] || python -W ignore shape_loop.py init $RUN --seed $SEED
n=$(grep -c . $RUN/log.jsonl 2>/dev/null || echo 0)
while [ "$n" -lt "$MAX" ]; do
  [ -f $RUN/STOP ] && { echo "LOOP_END stop file $(date -u)"; break; }
  python -W ignore shape_loop.py run $RUN --iters 1 > $RUN/last_run.out 2>&1; rc=$?
  tail -2 $RUN/last_run.out
  commit
  [ $rc -ne 0 ] && { echo "shape_loop exited $rc $(date -u)"; sleep 60; python -W ignore shape_loop.py run $RUN --iters 1 > $RUN/last_run.out 2>&1 || { echo "LOOP_END error twice $(date -u)"; break; }; commit; }
  grep -q "step below minimum" $RUN/last_run.out && { echo "LOOP_END converged $(date -u)"; break; }
  n=$(grep -c . $RUN/log.jsonl)
done
commit "best so far"
echo "LOOP_END done $(date -u)"
