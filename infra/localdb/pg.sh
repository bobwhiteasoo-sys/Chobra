#!/usr/bin/env bash
# Local PostgreSQL for development without Docker.
# Binaries come from the embedded-postgres npm package (run `npm install` here first).
# Usage: infra/localdb/pg.sh init|start|stop|status|reset
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BIN="$HERE/node_modules/@embedded-postgres/darwin-arm64/native/bin"
[ -d "$BIN" ] || BIN="$(ls -d "$HERE"/node_modules/@embedded-postgres/*/native/bin 2>/dev/null | head -1)"
DATA="${CHOBRA_PGDATA:-$ROOT/.localdb/data}"
PORT="${CHOBRA_PGPORT:-54329}"
LOG="$ROOT/.localdb/postgres.log"

if [ ! -x "$BIN/pg_ctl" ]; then
  echo "PostgreSQL binaries not found. Run: (cd infra/localdb && npm install)" >&2
  exit 1
fi

psql_exec() {
  # Runs SQL through psycopg so that no psql binary is required.
  "$ROOT/.venv/bin/python" - "$PORT" "$1" <<'PY'
import sys, psycopg
port, sql = sys.argv[1], sys.argv[2]
with psycopg.connect(host="127.0.0.1", port=int(port), user="postgres", dbname="postgres", autocommit=True) as c:
    c.execute(sql)
PY
}

case "${1:-}" in
  init)
    if [ -f "$DATA/PG_VERSION" ]; then echo "Already initialized: $DATA"; exit 0; fi
    mkdir -p "$(dirname "$DATA")"
    "$BIN/initdb" -D "$DATA" -U postgres --auth=trust --encoding=UTF8 --locale=C >/dev/null
    echo "listen_addresses = '127.0.0.1'" >> "$DATA/postgresql.conf"
    echo "Initialized $DATA"
    ;;
  start)
    "$0" init
    if "$BIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then echo "Already running on $PORT"; exit 0; fi
    "$BIN/pg_ctl" -D "$DATA" -o "-p $PORT" -l "$LOG" -w start >/dev/null
    # Roles: owner for migrations, app role that cannot bypass row level security.
    psql_exec "DO \$\$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='chobra_owner') THEN CREATE ROLE chobra_owner LOGIN; END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='chobra_app') THEN CREATE ROLE chobra_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF;
    END \$\$;" || true
    for db in chobra chobra_test; do
      psql_exec "CREATE DATABASE $db OWNER chobra_owner" 2>/dev/null || true
    done
    echo "PostgreSQL running on 127.0.0.1:$PORT (log: $LOG)"
    ;;
  stop)
    "$BIN/pg_ctl" -D "$DATA" -m fast stop || true
    ;;
  status)
    "$BIN/pg_ctl" -D "$DATA" status
    ;;
  reset)
    "$0" stop
    rm -rf "$DATA"
    "$0" start
    ;;
  *)
    echo "Usage: $0 init|start|stop|status|reset" >&2
    exit 2
    ;;
esac
