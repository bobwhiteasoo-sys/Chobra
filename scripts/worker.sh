#!/usr/bin/env bash
# Standalone worker process (production layout).
set -euo pipefail
source "$(dirname "$0")/env.sh"
exec "$CHOBRA_ROOT/.venv/bin/python" -m chobra_worker.main "$@"
