#!/usr/bin/env bash
# deploy/maintenance.sh — toggle the nginx maintenance page.
#
#   deploy/maintenance.sh on      # 503 + "технические работы" for users
#   deploy/maintenance.sh off     # back to normal
#   deploy/maintenance.sh status  # exit 0 = on, exit 1 = off
#
# While ON, nginx answers page requests with deploy/maintenance/_maintenance.html
# and /api/* with a fixed JSON body ({"code":"maintenance",...}) so the SPA can
# tell planned downtime from a real 5xx. /health, /healthz and the internal
# locations bypass the flag, so health checks and the deploy's own probes keep
# working.
#
# This is the FALLBACK path. A normal release is zero-downtime via the blue-green
# slots (deploy/deploy.sh) and never touches this flag.

set -euo pipefail

# shellcheck source=deploy/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  echo "usage: $(basename "$0") on|off|status" >&2
  exit 2
}

case "${1:-}" in
  on)
    if maintenance_is_on; then
      log "maintenance already ON — nothing to do"
      exit 0
    fi
    maintenance_on
    ;;
  off)
    if ! maintenance_is_on; then
      log "maintenance already OFF — nothing to do"
      exit 0
    fi
    maintenance_off
    ;;
  status)
    if maintenance_is_on; then
      log "maintenance: ON"
      exit 0
    fi
    log "maintenance: OFF"
    exit 1
    ;;
  *)
    usage
    ;;
esac
