"""`chobra-worker`: claims jobs and executes them. Several threads share one process."""
from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time

from chobra_api.db import SessionLocal

from .executor import HANDLERS, LeaseLost, execute_run
from .jobs import claim, finish

log = logging.getLogger("chobra.worker")


def run_one(owner: str) -> bool:
    db = SessionLocal()
    try:
        lease = claim(db, owner)
        if lease is None:
            return False
        log.info("job %s %s target=%s gen=%s", lease.kind, lease.job_id, lease.target_id, lease.generation)
        try:
            if lease.kind == "run.execute":
                execute_run(lease, db)
            else:
                HANDLERS[lease.kind](lease)
            finish(db, lease)
        except LeaseLost as exc:
            log.warning("lease lost: %s", exc)
        except Exception as exc:  # noqa: BLE001 - recorded on the job and retried with backoff
            log.exception("job failed")
            db.rollback()
            finish(db, lease, error=f"{type(exc).__name__}: {exc}"[:1000], retry_in=5)
        return True
    finally:
        db.close()


def loop(owner: str, stop: threading.Event, idle_sleep: float = 0.3) -> None:
    while not stop.is_set():
        if not run_one(owner):
            stop.wait(idle_sleep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chobra worker")
    parser.add_argument("--threads", type=int, default=int(os.environ.get("CHOBRA_WORKER_THREADS", "4")))
    parser.add_argument("--drain", action="store_true", help="process jobs until the queue is empty, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    base = f"{socket.gethostname()}:{os.getpid()}"
    if args.drain:
        while run_one(f"{base}:drain"):
            pass
        return
    stop = threading.Event()
    threads = [threading.Thread(target=loop, args=(f"{base}:{i}", stop), daemon=True) for i in range(args.threads)]
    for thread in threads:
        thread.start()
    log.info("worker started with %d threads", args.threads)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        for thread in threads:
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
