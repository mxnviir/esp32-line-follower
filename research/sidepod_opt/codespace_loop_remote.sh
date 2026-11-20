#!/bin/bash
# Runs INSIDE a GitHub Codespace (started by codespace_loop.sh from your PC). Sets the machine up
# (OpenFOAM v2412, Python deps, DAFoam image), then runs shape_loop.py for several seeds in
# parallel, one iteration at a time, committing and pushing each seed's history after every
# iteration. Log: /workspaces/loop_job.log.
#
#   SEEDS="original lean block" NP=4 ITERS=12 HOURS=10 bash research/sidepod_opt/codespace_loop_remote.sh
#
# Rule of thumb: each seed needs NP cores and ~16 GB RAM (DAFoam's Krylov adjoint peaks ~15 GB on
# the coarse mesh). A swap file is added when RAM is short.
set -x
exec >> /workspaces/loop_job.log 2>&1
SEEDS=${SEEDS:-"original lean block"}; NP=${NP:-4}; ITERS=${ITERS:-12}; HOURS=${HOURS:-10}
ROOT=/workspaces/esp32-line-follower
BRANCH=$(cd $ROOT && git rev-parse --abbrev-ref HEAD)
echo "START_SETUP $(date -u)"

# ---- system packages + OpenFOAM v2412 (same lines as codespace_gate.sh)
sudo apt-get update -q && sudo apt-get install -y -q libopengl0 libglu1-mesa libegl1 libgl1 libgomp1 libxkbcommon0
[ -d /usr/lib/openfoam/openfoam2412 ] || { curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash; sudo apt-get install -y -q openfoam2412-default; }

# ---- Python (pinned as in codespace_gate.sh)
if [ ! -x /workspaces/py/bin/python ]; then
  python3 -m pip install --break-system-packages -q uv && uv venv -p 3.11 /workspaces/py
  . /workspaces/py/bin/activate
  uv pip install -q numpy==2.4.6 scipy==1.17.1 pandas trimesh==5.2.0 scikit-image shapely rtree==1.4.1 mapbox-earcut \
    manifold3d==3.5.4 fast_simplification==0.2.0 jax jaxlib matplotlib pymeshlab==2025.7.post1 numba cadquery-ocp
fi
export PATH=/workspaces/py/bin:$PATH

# ---- DAFoam image (Docker Hub sometimes answers 429: retry)
for i in 1 2 3 4 5 6; do docker image inspect dafoam/opt-packages:v5.1.1 >/dev/null 2>&1 && break
  docker pull -q dafoam/opt-packages:v5.1.1 && break; sleep $((30 * i)); done

# ---- swap if RAM < 16 GB per seed
n=$(echo $SEEDS | wc -w); need=$((16 * n)); have=$(free -g | awk '/Mem/{print $2}')
if [ "$have" -lt "$need" ] && ! swapon --show | grep -q swapfile; then
  sudo fallocate -l $((need - have + 8))G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
fi
free -g; nproc

source /usr/lib/openfoam/openfoam2412/etc/bashrc
export OMPI_MCA_rmaps_base_oversubscribe=1 CFD_DIV_U="bounded Gauss upwind"
cd $ROOT/research/sidepod_opt
git config user.name "sidepod loop (codespace)"; git config user.email "noreply@github.com"

commit() {   # $1 = seed; serialised across seeds with a lock
  ( flock 9
    cd $ROOT
    d=research/sidepod_opt/runs/$1
    for f in $d/log.jsonl $d/config.json $d/state.json $d/last_run.out $d/it_*/cfd.json; do [ -e "$f" ] && git add -f "$f"; done
    if [ -n "$2" ]; then for f in $d/best_car $d/current.npz; do [ -e "$f" ] && git add -f "$f"; done; fi
    git commit -q -m "shape loop (codespace): seed $1 ${2:-iteration}

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoaxAjmcpDSsbf6r9F3" || exit 0
    for i in 1 2 3 4 5; do git pull -q --no-rebase --no-edit origin "$BRANCH" && git push -q origin HEAD:"$BRANCH" && break; sleep $((2 ** i)); done
  ) 9>/tmp/git.lock
}

echo "START_RUN $(date -u) seeds=[$SEEDS] np=$NP iters=$ITERS hours=$HOURS"
END=$(( $(date +%s) + HOURS * 3600 ))
for s in $SEEDS; do          # sequential: the first init builds the shared geometry cache
  [ -f runs/$s/state.json ] || python -W ignore shape_loop.py init runs/$s --seed $s --np $NP
done
for s in $SEEDS; do
  (
    for i in $(seq $ITERS); do
      [ "$(date +%s)" -gt "$END" ] && { echo "seed $s: time budget"; break; }
      python -W ignore shape_loop.py run runs/$s --iters 1 > runs/$s/last_run.out 2>&1; rc=$?
      cat runs/$s/last_run.out | tail -3
      commit $s
      [ $rc -ne 0 ] && { echo "seed $s: shape_loop exited $rc (see runs/$s/last_run.out)"; break; }
      grep -q "step below minimum" runs/$s/last_run.out && { echo "seed $s: converged"; break; }
    done
    commit $s final
    echo "SEED_DONE $s $(date -u)" ) &
done
wait
echo "LOOP_DONE $(date -u)"
