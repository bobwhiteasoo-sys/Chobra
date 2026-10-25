#!/usr/bin/env bash
# Local API with an embedded worker: PostgreSQL, migrations, then uvicorn on :8000.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$CHOBRA_ROOT"
infra/localdb/pg.sh start
(cd services/api && "$CHOBRA_ROOT/.venv/bin/alembic" -c alembic.ini upgrade head)
export CHOBRA_EMBEDDED_WORKER="${CHOBRA_EMBEDDED_WORKER:-1}"
exec "$CHOBRA_ROOT/.venv/bin/uvicorn" chobra_api.app:app --host 127.0.0.1 --port "${CHOBRA_API_PORT:-8000}"
