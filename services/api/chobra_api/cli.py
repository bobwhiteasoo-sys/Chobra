"""`chobra-api`: run the HTTP API with uvicorn."""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run("chobra_api.app:app", host=os.environ.get("CHOBRA_API_HOST", "127.0.0.1"), port=int(os.environ.get("CHOBRA_API_PORT", "8000")), proxy_headers=True)


if __name__ == "__main__":
    main()
