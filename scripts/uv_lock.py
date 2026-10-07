"""Temporarily expose the workspace lockfile at uv's required project path."""

import fcntl
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def run() -> int:
    root = Path(__file__).resolve().parent.parent
    state = root / ".bensz-api"
    state.mkdir(exist_ok=True)
    stored = state / "uv.lock"
    exposed = root / "uv.lock"
    with (state / "uv-wrapper.lock").open("a") as mutex:
        try:
            fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another scripts/uv.sh command is running; retry after it exits.", file=sys.stderr)
            return 1

        if exposed.is_symlink():
            if exposed.readlink() != Path(".bensz-api/uv.lock"):
                print("Refusing to replace an unexpected uv.lock symlink.", file=sys.stderr)
                return 1
        elif exposed.exists():
            if stored.exists() and exposed.read_bytes() != stored.read_bytes():
                print("Conflicting uv.lock files; reconcile them before running uv.", file=sys.stderr)
                return 1
            exposed.replace(stored)

        if not exposed.is_symlink():
            exposed.symlink_to(".bensz-api/uv.lock")

        child = None

        def forward(signum, _frame):
            if child is not None:
                child.send_signal(signum)

        handlers = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            child = subprocess.Popen(["uv", *sys.argv[1:]], cwd=root)
            result = child.wait()
            return result if result >= 0 else 128 - result
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
            # Preserve the new file if a uv version replaces the symlink atomically.
            if exposed.is_symlink():
                if exposed.readlink() == Path(".bensz-api/uv.lock"):
                    exposed.unlink()
            elif exposed.is_file():
                os.replace(exposed, stored)
            # Project policy permits Git metadata only in the root repository.
            for directory, dirs, files in os.walk(state / "uv-cache"):
                marker = Path(directory) / ".git"
                if ".git" in dirs:
                    dirs.remove(".git")
                    shutil.rmtree(marker)
                elif ".git" in files:
                    marker.unlink()


if __name__ == "__main__":
    sys.exit(run())
