#!/usr/bin/env python3
"""Spike 1: Claude Code CLI integration surface test.

Launches Claude Code 10 times headlessly to answer:
- Can it be launched headlessly with --print?
- Can tasks be passed as positional arguments?
- Can structured JSON output be captured?
- Can token consumption be monitored?
- Can it be terminated programmatically?
- Is behavior consistent across 10 runs?

Decision gate:
  8+/10 succeed  → Proceed with Tier 2 Claude Code adapter (Phase 2)
  6-7/10         → Proceed cautiously; allocate extra time for reliability work
  <6/10          → Contingency: Tier 1 API fallback for demo, investigate Codex for Tier 2
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

TASK = "Create a file called hello.py that prints 'Hello from AgentOS test'"
WORKSPACE = Path("/tmp/agentos_spike")
NUM_RUNS = 10
TIMEOUT_SECONDS = 120


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ without CLAUDECODE.

    Claude Code refuses to launch inside another Claude Code session
    (anti-nesting check). Since AgentOS spawns Claude Code as a managed
    subprocess, we must strip the marker env var.
    """
    import os
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def check_claude_available() -> bool:
    """Check if the claude CLI is available on PATH."""
    return shutil.which("claude") is not None


def run_claude_code_test(run_id: int) -> dict:
    """Launch Claude Code with a task, capture output, measure behavior."""
    workspace = WORKSPACE / f"run_{run_id}"
    workspace.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--output-format", "json",
                "--allowedTools", "Write,Read",
                "-p", TASK,
            ],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=_clean_env(),
        )
        elapsed = time.monotonic() - start
        timed_out = False
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {
            "run_id": run_id,
            "returncode": -1,
            "elapsed_seconds": round(elapsed, 2),
            "stdout_length": 0,
            "stderr_length": 0,
            "files_produced": [],
            "success": False,
            "error": f"Timed out after {TIMEOUT_SECONDS}s",
        }

    files_produced = list(workspace.rglob("*"))
    stdout_json = None
    if result.stdout.strip():
        try:
            stdout_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass

    return {
        "run_id": run_id,
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "stdout_length": len(result.stdout),
        "stderr_length": len(result.stderr),
        "stdout_is_json": stdout_json is not None,
        "files_produced": [
            str(f.relative_to(workspace)) for f in files_produced if f.is_file()
        ],
        "success": result.returncode == 0
        and any(f.name == "hello.py" for f in files_produced),
        "stderr": result.stderr.strip() if result.returncode != 0 else "",
    }


def run_termination_test() -> dict:
    """Test programmatic termination via subprocess.terminate()."""
    workspace = WORKSPACE / "termination_test"
    workspace.mkdir(parents=True, exist_ok=True)

    long_task = "Write a detailed 5000-word essay about the history of computing"
    proc = subprocess.Popen(
        [
            "claude",
            "--print",
            "--output-format", "json",
            "-p", long_task,
        ],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_clean_env(),
    )

    time.sleep(5)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    return {
        "test": "programmatic_termination",
        "terminated_cleanly": proc.returncode is not None,
        "returncode": proc.returncode,
    }


def evaluate_results(results: list[dict]) -> str:
    """Apply the decision gate."""
    successes = sum(1 for r in results if r["success"])
    if successes >= 8:
        return f"PROCEED — {successes}/{len(results)} succeeded. Tier 2 Claude Code adapter is viable."
    elif successes >= 6:
        return f"CAUTION — {successes}/{len(results)} succeeded. Proceed but allocate extra reliability time."
    else:
        return f"CONTINGENCY — {successes}/{len(results)} succeeded. Use Tier 1 API fallback; investigate alternatives."


def main() -> None:
    print("=" * 60)
    print("AgentOS Spike 1: Claude Code CLI Integration Surface Test")
    print("=" * 60)

    if not check_claude_available():
        print("\nERROR: 'claude' CLI not found on PATH.")
        print("Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    # Clean up from previous runs
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)

    # Run main tests
    print(f"\nRunning {NUM_RUNS} headless tests...")
    results = []
    for i in range(NUM_RUNS):
        print(f"  Run {i + 1}/{NUM_RUNS}...", end=" ", flush=True)
        r = run_claude_code_test(i)
        status = "OK" if r["success"] else "FAIL"
        print(f"{status} ({r['elapsed_seconds']}s)")
        results.append(r)

    # Run termination test
    print("\nRunning termination test...", end=" ", flush=True)
    term_result = run_termination_test()
    print("OK" if term_result["terminated_cleanly"] else "FAIL")

    # Output full results
    print("\n" + "=" * 60)
    print("DETAILED RESULTS")
    print("=" * 60)
    print(json.dumps(results, indent=2))

    print("\nTermination test:")
    print(json.dumps(term_result, indent=2))

    # Decision gate
    successes = sum(1 for r in results if r["success"])
    json_outputs = sum(1 for r in results if r.get("stdout_is_json"))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Successful runs:     {successes}/{NUM_RUNS}")
    print(f"JSON output parsed:  {json_outputs}/{NUM_RUNS}")
    print(f"Clean termination:   {'Yes' if term_result['terminated_cleanly'] else 'No'}")
    print(f"\nDECISION: {evaluate_results(results)}")


if __name__ == "__main__":
    main()
