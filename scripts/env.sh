# Source me: Python paths for the monorepo packages (does not rely on .pth files).
CHOBRA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$CHOBRA_ROOT/packages/engine:$CHOBRA_ROOT/packages/environments:$CHOBRA_ROOT/packages/agents:$CHOBRA_ROOT/packages/audit:$CHOBRA_ROOT/packages/reporting:$CHOBRA_ROOT/services/api:$CHOBRA_ROOT/services/worker${PYTHONPATH:+:$PYTHONPATH}"
