#!/bin/bash
# this machine, after the medium scatter queue: smoke test of every campaign stage (coarse, not committed),
# the wall-resolved BC check, then the medium runs still missing (ROUTES.md 2026-11-21 13:00)
cd /home/user/esp32-line-follower/research/sidepod_opt
until grep -q SCATTER_DONE gate/scatter_medium_queue.log; do sleep 30; done
swapon --show | grep -q swapfile || swapon /swapfile 2>/dev/null
docker info >/dev/null 2>&1 || { (dockerd > gate/dockerd.log 2>&1 &); sleep 10; }
export PY=/opt/py/bin/python
C=fine_campaign/campaign.sh
[ -f runs/fine_cars/win5/car/car_half.stl ] || bash $C cars
echo "== smoke $(date -u +%T)"
export RES=coarse TAG=smoke NP=4 PUSH=0 SMOKE=1
ITERS=300 ONLY=team bash $C forward
ITERS=300 STEADY_ITERS=300 bash $C steady
BUMP_ITERS=100 JOBS=2 NP=2 bash $C bumps
DAF_PRIMAL_ONLY=1 DAF_PRIMAL_ITERS=20 bash $C adjoint
bash $C summary > /dev/null; git -C ../.. reset -q research/sidepod_opt/fine_campaign/SUMMARY_smoke.md 2>/dev/null
echo "SMOKE_DONE $(date -u +%T)"
unset TAG SMOKE PUSH
echo "== bccheck $(date -u +%T)"
RES=coarse NP=4 ITERS=2000 bash $C bccheck
echo "== medium additions $(date -u +%T)"
RES=medium TAG=medium NP=4 ITERS=2000 ONLY="blend50 blend75 win5 nopod_p05 win3_p05 blend50_p05 blend75_p05" bash $C forward
echo "CAMPAIGN_HERE_DONE $(date -u +%T)"
