#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/kilted/setup.bash
if [[ -n "${RMF_WORKSPACE_SETUP:-}" ]]; then source "$RMF_WORKSPACE_SETUP"; fi
exec ros2 launch rmf_demos_gz office.launch.xml use_sim_time:=true sim_update_rate:=100

