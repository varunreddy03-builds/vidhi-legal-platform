"""Runs the API under `coverage` so a test run can report which application lines the tests really executed.

Used by `scripts/test-backend.ps1 -Coverage`. Not for production. The server stops when the file named in COV_STOP_FILE appears, so coverage can write its data
(killing the process on Windows would lose it).

    python scripts/cov_server.py <port>    (run from the backend folder)"""

import os
import sys
import threading
import time

import coverage

sys.path.insert(0, os.getcwd())  # the backend folder, so "server:app" can be imported
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
stop = os.environ["COV_STOP_FILE"]
cov = coverage.Coverage(source=["lib", "routers", "models"], data_file=os.environ.get("COV_DATA_FILE", ".coverage"))
cov.start()

import uvicorn  # noqa: E402  (imported after coverage starts, so import-time lines count)

server = uvicorn.Server(uvicorn.Config("server:app", port=port, log_level="warning"))


def watch() -> None:
    while not os.path.exists(stop):
        time.sleep(1)
    server.should_exit = True


threading.Thread(target=watch, daemon=True).start()
try:
    server.run()
finally:
    cov.stop()
    cov.save()
