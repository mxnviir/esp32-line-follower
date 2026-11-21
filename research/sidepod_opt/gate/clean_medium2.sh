#!/bin/bash
# the reference first: more clean team repeats (team~1 read 177.74 vs 179.86), then the medium singles
cd /home/user/esp32-line-follower/research/sidepod_opt
export PY=/opt/py/bin/python RES=medium TAG=medium NP=4 ITERS=2000
FORWARD_LIST="team~2 team~3 blend50 blend75 win5" bash fine_campaign/campaign.sh forward
echo CLEAN_MEDIUM_DONE
