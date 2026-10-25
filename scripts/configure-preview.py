#!/usr/bin/env python3
"""Create private preview configuration once. Never emits secrets to stdout."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
domain = sys.argv[1] if len(sys.argv) == 2 else ""
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", domain):
    raise SystemExit("Usage: scripts/configure-preview.py example.com")
target = root / ".env.deploy"
if target.exists():
    raise SystemExit(".env.deploy already exists; preserve its database passwords and encryption key")
preview_password = secrets.token_urlsafe(24)
image = "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
result = subprocess.run(["docker", "run", "--rm", "--entrypoint", "caddy", image, "hash-password", "--plaintext", preview_password], text=True, capture_output=True, check=True)
values = {"CHOBRA_DOMAIN": domain, "CHOBRA_PREVIEW_USER": "chobra", "CHOBRA_PREVIEW_HASH": result.stdout.strip(), **{key: secrets.token_urlsafe(32) for key in ("POSTGRES_PASSWORD", "CHOBRA_OWNER_PASSWORD", "CHOBRA_APP_PASSWORD", "CHOBRA_SIGNING_KEY", "CHOBRA_SECRETS_KEY")}}
os.umask(0o077)
target.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n")
(root / "preview-access.txt").write_text(f"https://{domain}\nПользователь: chobra\nПароль: {preview_password}\n\nЭто закрытый стенд с dev-входом. Не используйте его как публичную систему идентификации.\n")
print("Created .env.deploy and preview-access.txt with permissions 0600")
