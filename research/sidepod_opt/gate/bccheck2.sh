#!/bin/bash
# wall-resolved BC check again, now with the layer stack really on (ROUTES.md 2026-11-21 14:50)
cd /home/user/esp32-line-follower/research/sidepod_opt
until grep -q CAMPAIGN_HERE_DONE gate/campaign_here.log; do sleep 30; done
PY=/opt/py/bin/python RES=coarse NP=4 ITERS=2000 bash fine_campaign/campaign.sh bccheck
echo BCCHECK2_DONE
