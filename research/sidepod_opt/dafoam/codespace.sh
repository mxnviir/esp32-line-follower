#!/bin/bash
# DAFoam drag gradient on a GitHub Codespace (8 cores, 32 GB; Docker is built into the default image).
# Start it from YOUR PC:
#
#   export GH_TOKEN=$(gh auth token --user <account>)
#   bash research/sidepod_opt/dafoam/codespace.sh start     # create, then state A + DAFoam in the background
#   bash research/sidepod_opt/dafoam/codespace.sh check     # at least every 3 h (idle timeout 240 min)
#   bash research/sidepod_opt/dafoam/codespace.sh delete    # when check shows DAFOAM_REMOTE_DONE (4 core-h per hour)
#
# The codespace solves its own state A (Part 2's pipeline), then DAFoam's primal and adjoint, and
# commits dafoam_sens.json/.npz under gate_results_cs/dafoam/ (pushed to the branch).
set -e
REPO=${REPO:-mxnviir/stem-racing-paper}
BRANCH=${BRANCH:-ccr-a4f3e46d-23atrh}
STATE=${STATE:-$HOME/.sidepod_dafoam_codespace}
NP=${NP:-8}; ITERS=${ITERS:-300}

case "$1" in
start)
  CS=$(gh codespace create -R "$REPO" -b "$BRANCH" -m standardLinux32gb --idle-timeout 240m \
         --retention-period 24h -d "sidepod DAFoam adjoint")
  echo "$CS" > "$STATE"; echo "codespace: $CS"
  gh codespace ssh -c "$CS" -- "cat > /tmp/run.sh <<'EOF'
#!/bin/bash
set -x
exec > /workspaces/dafoam_job.log 2>&1
cd /workspaces/stem-racing-paper
python3 -m pip install --break-system-packages -q uv && uv venv -p 3.11 /workspaces/py && . /workspaces/py/bin/activate
uv pip install -q numpy==2.4.6 scipy==1.17.1 pandas trimesh==5.2.0 scikit-image shapely rtree==1.4.1 mapbox-earcut \
  manifold3d==3.5.4 fast_simplification==0.2.0 jax jaxlib matplotlib pymeshlab==2025.7.post1 numba cadquery-ocp
cd research/sidepod_opt
echo START_RUN; date -u
dafoam/remote_run.sh /workspaces/stem-racing-paper/research/sidepod_opt/gate_results_cs/dafoam $NP $ITERS
echo EXIT \$?; date -u
git config user.name 'sidepod dafoam (codespace)'; git config user.email 'noreply@github.com'
git add gate_results_cs/dafoam && git commit -q -m 'DAFoam gradient (codespace)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019HSvoZEkpXwbb9LF44Vpfg' && \
  for i in 1 2 3 4; do git pull -q --no-rebase --no-edit origin HEAD; git push -q origin HEAD && break; sleep \$((2**i)); done
EOF
chmod +x /tmp/run.sh; setsid nohup /tmp/run.sh >/dev/null 2>&1 </dev/null &"
  ;;
check)
  CS=$(cat "$STATE")
  gh codespace ssh -c "$CS" -- 'grep -E "START_RUN|EXIT|DAFOAM" /workspaces/dafoam_job.log; tail -3 /workspaces/dafoam_job.log'
  ;;
delete)
  CS=$(cat "$STATE"); gh codespace delete -c "$CS" -f && rm -f "$STATE"
  ;;
*)
  echo "usage: $0 start|check|delete"; exit 1
  ;;
esac
