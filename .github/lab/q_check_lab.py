"""Queue self-check lab (no project code): `ok [seconds]` sleeps then passes, `fail` exits 1 with a
message, `env` prints the queue-related environment. Used by the panel's pre-tests to prove the
worker's paths: pass, fail + retry, looping slots."""
import os
import sys
import time

what = sys.argv[1] if len(sys.argv) > 1 else "ok"
if what == "ok":
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
    print("LAB check ok", sys.argv[1:])
elif what == "fail":
    print("LAB check failing on purpose")
    sys.exit("planned failure: this job tests the retry and failure report")
elif what == "env":
    for k in sorted(os.environ):
        if k.startswith("P2_"):
            print("LAB env", k, os.environ[k])
