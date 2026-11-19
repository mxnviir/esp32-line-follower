#!/bin/bash
# Run the adjoint accuracy test (or continue it) on a GitHub Codespace. Start it from YOUR PC:
#
#   export GH_TOKEN=$(gh auth token --user <account>)        # never gh auth switch
#   bash research/sidepod_opt/codespace_gate.sh start        # creates the codespace, starts the queue
#   bash research/sidepod_opt/codespace_gate.sh check        # at least every 3 h (idle timeout 240 min)
#   bash research/sidepod_opt/codespace_gate.sh fetch        # copies gate_results/ back here
#   bash research/sidepod_opt/codespace_gate.sh delete       # straight after fetch (it costs 4 core-h per hour)
#
# The codespace builds everything from the repo itself (STEP -> exact meshes -> bumps): no case
# folders or STLs travel through git. Results are also committed and pushed from the codespace
# to this branch after every job (gate_queue.sh), so `fetch` is only a backup.
set -e
REPO=${REPO:-mxnviir/esp32-line-follower}
BRANCH=${BRANCH:-ccr-a4f3e46d-23atrh}
STATE=${STATE:-$HOME/.sidepod_gate_codespace}

case "$1" in
start)
  CS=$(gh codespace create -R "$REPO" -b "$BRANCH" -m standardLinux32gb --idle-timeout 240m \
         --retention-period 24h -d "sidepod adjoint gate")
  echo "$CS" > "$STATE"; echo "codespace: $CS"
  gh codespace ssh -c "$CS" -- 'cat > /tmp/run.sh <<"EOF"
#!/bin/bash
set -x
exec > /workspaces/gate_job.log 2>&1
cd /workspaces/esp32-line-follower
sudo apt-get update -q && sudo apt-get install -y -q libopengl0 libglu1-mesa libegl1 libgl1 libgomp1 libxkbcommon0
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get install -y -q openfoam2412-default
python3 -m pip install --break-system-packages -q uv && uv venv -p 3.11 /workspaces/py && . /workspaces/py/bin/activate
uv pip install -q numpy==2.4.6 scipy==1.17.1 pandas trimesh==5.2.0 scikit-image shapely rtree==1.4.1 mapbox-earcut \
  manifold3d==3.5.4 fast_simplification==0.2.0 jax jaxlib matplotlib pymeshlab==2025.7.post1 numba cadquery-ocp
cd research/sidepod_opt
python - <<PY
from pathlib import Path
from geometry import Car
c = Car(); c.export_car_folder(c.body_mesh, Path("gate/original"), "original")
PY
python gate.py bumps
echo START_RUN; date -u
( ./gate_run.sh base base 4 ) && ./gate_queue.sh
echo EXIT $?; date -u
EOF
chmod +x /tmp/run.sh; setsid nohup /tmp/run.sh >/dev/null 2>&1 </dev/null &'
  ;;
check)
  CS=$(cat "$STATE")
  gh codespace ssh -c "$CS" -- 'grep -E "START_RUN|EXIT" /workspaces/gate_job.log; tail -2 /workspaces/gate_job.log; \
     ls /workspaces/esp32-line-follower/research/sidepod_opt/gate_results/'
  ;;
fetch)
  CS=$(cat "$STATE")
  mkdir -p gate_results_codespace
  gh codespace cp -c "$CS" -e -r 'remote:/workspaces/esp32-line-follower/research/sidepod_opt/gate_results' ./gate_results_codespace/
  ;;
delete)
  gh codespace delete -c "$(cat "$STATE")" -f && rm -f "$STATE"
  ;;
*) echo "usage: $0 start|check|fetch|delete"; exit 2 ;;
esac
