#!/bin/bash
# clean medium repeat meshes (same STL, shifted meshing frame) + the medium singles (ROUTES.md 2026-11-21 16:05)
cd /home/user/esp32-line-follower/research/sidepod_opt
export PY=/opt/py/bin/python RES=medium TAG=medium NP=4 ITERS=2000
FORWARD_ORDER="groove~1 groove~2 adjoint8~1 adjoint8~2 team~1 blend50 blend75 win5"
FORWARD_LIST="$FORWARD_ORDER" bash fine_campaign/campaign.sh forward
echo CLEAN_MEDIUM_DONE
