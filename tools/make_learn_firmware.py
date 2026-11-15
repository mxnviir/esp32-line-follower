#!/usr/bin/env python3
"""
Builds the TrackLearn sketch from AllInOne, so both always share the exact
same driving code (the learning run must drive like the race run).

  python3 tools/make_learn_firmware.py

Writes TrackLearn/TrackLearn.ino = AllInOne.ino with TRACK_LEARN_MODE 1.
Run it again after every change to AllInOne.ino.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, 'AllInOne', 'AllInOne.ino')).read()
out_dir = os.path.join(ROOT, 'TrackLearn')
os.makedirs(out_dir, exist_ok=True)
header = ("// GENERATED from AllInOne/AllInOne.ino by tools/make_learn_firmware.py.\n"
          "// Do not edit: change AllInOne.ino and run the script again.\n"
          "#define TRACK_LEARN_MODE 1\n\n")
open(os.path.join(out_dir, 'TrackLearn.ino'), 'w').write(header + src)
# same build options (40 MHz flash) as the race firmware
yaml = os.path.join(ROOT, 'AllInOne', 'sketch.yaml')
if os.path.exists(yaml):
    open(os.path.join(out_dir, 'sketch.yaml'), 'w').write(open(yaml).read())
print("Wrote TrackLearn/TrackLearn.ino (learning mode)")
