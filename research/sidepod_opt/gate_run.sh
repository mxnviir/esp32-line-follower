#!/bin/bash
# detached job runner: survives the session; log in gate/job_<name>.log
cd "$(dirname "$0")"
source /usr/lib/openfoam/openfoam2412/etc/bashrc
export OMPI_MCA_hwloc_base_use_hwthreads_as_cpus=1 OMPI_MCA_rmaps_base_oversubscribe=1 OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
name=$1; shift
echo START $(date -u) >> gate/job_$name.log
python -W ignore gate.py "$@" >> gate/job_$name.log 2>&1
echo EXIT $? $(date -u) >> gate/job_$name.log
