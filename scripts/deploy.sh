#!/usr/bin/env bash
# Upload a committed source snapshot. Private SSH keys are never copied to the server.
set -euo pipefail
DEPLOY_HOST="${1:?Usage: CHOBRA_DEPLOY_KEY=/path/to/key scripts/deploy.sh IP DOMAIN}"
DEPLOY_DOMAIN="${2:?Specify the application domain}"
DEPLOY_KEY="${CHOBRA_DEPLOY_KEY:?Specify CHOBRA_DEPLOY_KEY}"
[[ "$DEPLOY_HOST" =~ ^[0-9.]+$ && "$DEPLOY_DOMAIN" =~ ^[a-z0-9.-]+$ ]] || { echo "Invalid host or domain" >&2; exit 2; }
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -i "$DEPLOY_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=${CHOBRA_DEPLOY_KNOWN_HOSTS:-$DEPLOY_KEY.known_hosts}" -o ConnectTimeout=20 "root@$DEPLOY_HOST")
"${SSH[@]}" 'command -v docker >/dev/null && docker compose version >/dev/null && mkdir -p /opt/chobra'
git -C "$REPO_ROOT" archive HEAD | "${SSH[@]}" 'tar -x -C /opt/chobra'
"${SSH[@]}" bash -s -- "$DEPLOY_DOMAIN" <<'REMOTE'
set -euo pipefail
cd /opt/chobra
if [ ! -f .env.deploy ]; then python3 scripts/configure-preview.py "$1"; fi
docker compose --env-file .env.deploy -f infra/compose.production.yml config --quiet
docker compose --env-file .env.deploy -f infra/compose.production.yml up -d --build --wait
docker compose --env-file .env.deploy -f infra/compose.production.yml ps
echo 'Preview credentials are in /opt/chobra/preview-access.txt (0600).'
REMOTE
