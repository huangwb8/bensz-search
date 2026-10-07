"""Exercise the wrapper's lockfile lifecycle independently of app dependencies."""

import fcntl
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project with spaces"
    (root / "scripts").mkdir(parents=True)
    for name in ("uv.sh", "uv_lock.py"):
        shutil.copy(PROJECT / "scripts" / name, root / "scripts" / name)
    (root / ".bensz-api").mkdir()
    return root


def fake_uv(root, body):
    binary = root / "bin" / "uv"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nimport os, sys\n{body}\n")
    binary.chmod(0o755)
    return {**os.environ, "PATH": f"{binary.parent}:{os.environ['PATH']}"}


def invoke(root, env, *args):
    return subprocess.run(["sh", str(root / "scripts/uv.sh"), *args], env=env, capture_output=True, text=True)


def test_real_uv_generates_and_checks_stored_lock(workspace):
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    (workspace / "pyproject.toml").write_text(
        '[project]\nname="lock-probe"\nversion="0.0.0"\nrequires-python=">=3.11"\ndependencies=[]\n'
    )
    for args in (("lock", "--offline"), ("lock", "--check", "--offline")):
        result = invoke(workspace, os.environ, *args)
        assert result.returncode == 0, result.stderr
        assert (workspace / ".bensz-api/uv.lock").is_file()
        assert not (workspace / "uv.lock").is_symlink()
        assert not (workspace / "uv.lock").exists()


@pytest.mark.parametrize("atomic_replace", [False, True])
def test_failed_uv_keeps_updates_and_cleans_links(workspace, atomic_replace):
    (workspace / ".bensz-api/uv.lock").write_text("old")
    cache = workspace / ".bensz-api/uv-cache"
    (cache / "checkout/.git").mkdir(parents=True)
    (cache / "marker").mkdir()
    (cache / "marker/.git").write_text("git marker")
    body = "lock = Path('uv.lock')\nassert lock.is_symlink()\n"
    if atomic_replace:
        body += "lock.unlink()\n"
    body += "lock.write_text('updated')\nsys.exit(7)"
    result = invoke(workspace, fake_uv(workspace, body))
    assert result.returncode == 7
    assert (workspace / ".bensz-api/uv.lock").read_text() == "updated"
    assert not (workspace / "uv.lock").exists()
    assert not (workspace / "uv.lock").is_symlink()
    assert not list(cache.rglob(".git"))


def test_migrates_legacy_lock_without_changing_arguments(workspace):
    (workspace / "uv.lock").write_text("legacy")
    result = invoke(
        workspace,
        fake_uv(workspace, "assert sys.argv[1:] == ['run', 'argument with spaces']"),
        "run",
        "argument with spaces",
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / ".bensz-api/uv.lock").read_text() == "legacy"
    assert not (workspace / "uv.lock").exists()


def test_conflicting_locks_are_preserved(workspace):
    (workspace / "uv.lock").write_text("root")
    (workspace / ".bensz-api/uv.lock").write_text("stored")
    result = invoke(workspace, fake_uv(workspace, "raise AssertionError('must not run')"))
    assert result.returncode == 1
    assert "Conflicting" in result.stderr
    assert (workspace / "uv.lock").read_text() == "root"
    assert (workspace / ".bensz-api/uv.lock").read_text() == "stored"


def test_concurrent_wrapper_does_not_touch_active_lock(workspace):
    exposed = workspace / "uv.lock"
    exposed.symlink_to(".bensz-api/uv.lock")
    with (workspace / ".bensz-api/uv-wrapper.lock").open("a") as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        result = invoke(workspace, fake_uv(workspace, "raise AssertionError('must not run')"))
        assert result.returncode == 1
        assert "Another scripts/uv.sh" in result.stderr
        assert exposed.is_symlink()


def test_termination_forwards_signal_and_removes_link(workspace):
    env = fake_uv(workspace, "import time\nPath('ready').touch()\ntime.sleep(60)")
    process = subprocess.Popen(["sh", str(workspace / "scripts/uv.sh")], env=env)
    try:
        deadline = time.monotonic() + 5
        while not (workspace / "ready").exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 143
        assert not (workspace / "uv.lock").is_symlink()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_build_and_git_rules_include_only_workspace_lock():
    stored = ".bensz-api/uv.lock"
    for name in ("Dockerfile", "Dockerfile.patch"):
        dockerfile = PROJECT / "docs/deploy" / name
        assert stored in dockerfile.read_text()
        assert "sh scripts/uv.sh sync --frozen" in dockerfile.read_text()
        rules = Path(f"{dockerfile}.dockerignore").read_text().splitlines()
        assert ".bensz-api/*" in rules
        assert f"!{stored}" in rules
    result = subprocess.run(["git", "check-ignore", "--no-index", stored], cwd=PROJECT, capture_output=True)
    assert result.returncode == 1
