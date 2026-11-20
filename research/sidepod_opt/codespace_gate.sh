#!/bin/bash
# Run the adjoint accuracy test (or continue it) on a GitHub Codespace. Start it from YOUR PC:
#
#   export GH_TOKEN=$(gh auth token --user <account>)        # never gh auth switch
#   bash research/sidepod_opt/codespace_gate.sh start        # creates the codespace, starts the queue
#   GATE_JOBS="name:site:mm ..." bash ... start              # other bumps (see gate_cs_queue.sh)
#   bash research/sidepod_opt/codespace_gate.sh check        # at least every 3 h (idle timeout 240 min)
#   bash research/sidepod_opt/codespace_gate.sh fetch        # copies gate_results/ back here
#   bash research/sidepod_opt/codespace_gate.sh delete       # straight after fetch (it costs 4 core-h per hour)
#
# The codespace builds everything from the repo itself (STEP -> exact meshes -> bumps): no case
# folders or STLs travel through git. It solves its own state A and zero run (8 cores), then the
# bumps 3 at a time; the adjoint is the one already in gate_results/ (not re-run). Results go to
# gate_results_cs/ and are committed and pushed after every job, so `fetch` is only a backup.
set -e
REPO=${REPO:-mxnviir/stem-racing-paper}
BRANCH=${BRANCH:-ccr-a4f3e46d-23atrh}
STATE=${STATE:-$HOME/.sidepod_gate_codespace}

case "$1" in
start)
  : "${GATE_JOBS:?set GATE_JOBS first (see gate_cs_queue.sh); nothing was created}"
  CS=$(gh codespace create -R "$REPO" -b "$BRANCH" -m standardLinux32gb --idle-timeout 240m \
         --retention-period 24h -d "sidepod adjoint gate")
  echo "$CS" > "$STATE"; echo "codespace: $CS"
  # no default job list: what is worth paid hours depends on the matched-adjoint result
  # (gate_results/judge.json). Pass GATE_JOBS explicitly, e.g. GATE_JOBS="adjoint_matched: grad_p15:grad:1.5 grad_m15:grad:-1.5"
  JOBS=${GATE_JOBS:?set GATE_JOBS (see gate_cs_queue.sh)}
  gh codespace ssh -c "$CS" -- "echo 'GATE_JOBS=\"$JOBS\"' > /tmp/jobs.env"
  gh codespace ssh -c "$CS" -- 'cat > /tmp/run.sh <<"EOF"
#!/bin/bash
set -x
exec > /workspaces/gate_job.log 2>&1
. /tmp/jobs.env
cd /workspaces/stem-racing-paper
sudo apt-get update -q && sudo apt-get install -y -q libopengl0 libglu1-mesa libegl1 libgl1 libgomp1 libxkbcommon0
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get install -y -q openfoam2412-default
python3 -m pip install --break-system-packages -q uv && uv venv -p 3.11 /workspaces/py && . /workspaces/py/bin/activate
uv pip install -q numpy==2.4.6 scipy==1.17.1 pandas trimesh==5.2.0 scikit-image shapely rtree==1.4.1 mapbox-earcut \
  manifold3d==3.5.4 fast_simplification==0.2.0 jax jaxlib matplotlib pymeshlab==2025.7.post1 numba cadquery-ocp
cd research/sidepod_opt
git config user.name "sidepod gate (codespace)"; git config user.email "noreply@github.com"
echo START_RUN; date -u
GATE_JOBS="$GATE_JOBS" LANES=3 NP_BASE=6 ./gate_cs_queue.sh
echo EXIT $?; date -u
EOF
chmod +x /tmp/run.sh; setsid nohup /tmp/run.sh >/dev/null 2>&1 </dev/null &'
  ;;
check)
  CS=$(cat "$STATE")
  gh codespace ssh -c "$CS" -- 'grep -E "START_RUN|EXIT" /workspaces/gate_job.log; tail -2 /workspaces/gate_job.log; \
     ls /workspaces/stem-racing-paper/research/sidepod_opt/gate_results_cs/'
  ;;
fetch)
  CS=$(cat "$STATE")
  mkdir -p gate_results_codespace
  gh codespace cp -c "$CS" -e -r 'remote:/workspaces/stem-racing-paper/research/sidepod_opt/gate_results_cs' ./gate_results_codespace/
  ;;
delete)
  gh codespace delete -c "$(cat "$STATE")" -f && rm -f "$STATE"
  ;;
*) echo "usage: $0 start|check|fetch|delete"; exit 2 ;;
esac
