#!/bin/bash
# Run the free-form sidepod search (shape_loop.py) on a GitHub Codespace. Run this from YOUR PC
# (Git Bash or WSL on Windows), with the GitHub CLI signed in.
#
#   bash research/sidepod_opt/codespace_loop.sh machines        # machine types your account can use
#   MACHINE=largePremiumLinux SEEDS="original lean block" NP=4 bash research/sidepod_opt/codespace_loop.sh start
#   bash research/sidepod_opt/codespace_loop.sh check           # every 1-3 h (idle timeout is 240 min)
#   bash research/sidepod_opt/codespace_loop.sh log             # last 40 lines of the job log
#   bash research/sidepod_opt/codespace_loop.sh delete          # when check shows LOOP_DONE (it bills per core-hour)
#
# Results are committed and pushed to the branch by the codespace itself after every iteration
# (research/sidepod_opt/runs/<seed>/), so `git pull` on your PC shows progress.
set -e
REPO=${REPO:-mxnviir/stem-racing-paper}
BRANCH=${BRANCH:-claude/dazzling-ritchie-3q792g}
STATE=${STATE:-$HOME/.sidepod_loop_codespace}
MACHINE=${MACHINE:-largePremiumLinux}
SEEDS=${SEEDS:-"original lean block"}; NP=${NP:-4}; ITERS=${ITERS:-12}; HOURS=${HOURS:-10}

case "$1" in
machines)
  gh api "repos/$REPO/codespaces/machines?ref=$BRANCH" --jq '.machines[] | "\(.name)\t\(.cpus) cores\t\(.memory_in_bytes/1073741824|floor) GB"'
  ;;
start)
  CS=$(gh codespace create -R "$REPO" -b "$BRANCH" -m "$MACHINE" --idle-timeout 240m \
         --retention-period 48h -d "sidepod shape loop")
  echo "$CS" > "$STATE"; echo "codespace: $CS"
  gh codespace ssh -c "$CS" -- "cd /workspaces/stem-racing-paper && git pull -q origin $BRANCH; \
    SEEDS='$SEEDS' NP=$NP ITERS=$ITERS HOURS=$HOURS setsid nohup bash research/sidepod_opt/codespace_loop_remote.sh \
    >/dev/null 2>&1 </dev/null & echo launched"
  ;;
check)
  CS=$(cat "$STATE")
  gh codespace ssh -c "$CS" -- 'grep -E "START_SETUP|START_RUN|SEED_DONE|LOOP_DONE|exited|converged|time budget" /workspaces/loop_job.log; \
     cd /workspaces/stem-racing-paper/research/sidepod_opt; for s in runs/*/; do echo "== $s"; \
     [ -f $s/log.jsonl ] && tail -2 $s/log.jsonl | cut -c1-300; done; free -g | head -2; uptime'
  ;;
log)
  gh codespace ssh -c "$(cat "$STATE")" -- 'tail -40 /workspaces/loop_job.log'
  ;;
delete)
  gh codespace delete -c "$(cat "$STATE")" -f && rm -f "$STATE"
  ;;
*) echo "usage: $0 machines|start|check|log|delete"; exit 2 ;;
esac
