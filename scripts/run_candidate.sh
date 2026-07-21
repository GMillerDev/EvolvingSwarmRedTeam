#!/usr/bin/env bash
set -euo pipefail
aft run-scenario --config "${1:-configs/default.yaml}" --scenario "${2:-configs/example_scenario.yaml}"

