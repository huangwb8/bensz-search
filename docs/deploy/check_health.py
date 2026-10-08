"""Read-only Docker health check suitable for an external monitoring timer."""

import argparse
import json
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container")
    args = parser.parse_args()
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .State}}", "--", args.container],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "unavailable", "action": "inspect the container or Docker service"}))
        return 2
    if result.returncode:
        print(json.dumps({"status": "unavailable", "action": "inspect the container or Docker service"}))
        return 2
    try:
        state = json.loads(result.stdout)
        if not isinstance(state, dict):
            raise ValueError("Invalid container state")
    except (ValueError, TypeError):
        print(json.dumps({"status": "unavailable", "action": "inspect the container or Docker service"}))
        return 2
    health = state.get("Health", {}).get("Status", "missing")
    ok = state.get("Running") and health == "healthy" and not state.get("OOMKilled")
    print(
        json.dumps(
            {
                "running": bool(state.get("Running")),
                "health": health,
                "oom_killed": bool(state.get("OOMKilled")),
                "action": "none" if ok else "alert operator; inspect resource usage and logs before recovery",
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
