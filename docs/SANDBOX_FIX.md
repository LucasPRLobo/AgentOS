# Sandbox Feature — Issues and Fix Plan

## Current State

The sandbox system (`agentos/security/sandbox.py`) provides three isolation levels for agent execution:

| Level | Implementation | Status |
|-------|---------------|--------|
| `none` | `NoopSandbox` — direct `subprocess.run` | Working |
| `namespace` | `NamespaceSandbox` — Linux `unshare(2)` | Broken without root |
| `container` | `ContainerSandbox` — Docker | Untested, requires Docker |

## The Problem

### `namespace` level fails immediately (exit code 1, 0.0s)

`NamespaceSandbox.run()` prepends `unshare --pid --mount --fork [--net]` to every command:

```python
# agentos/security/sandbox.py:56-60
def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    unshare_flags = ["unshare", "--pid", "--mount", "--fork"]
    if not self._config.network_enabled:
        unshare_flags.append("--net")
    return subprocess.run(unshare_flags + cmd, cwd=self._workspace, **kwargs)
```

This requires **root privileges** (or `CAP_SYS_ADMIN` capability). Without them, `unshare` fails silently and returns exit code 1. The adapter sees this as "Claude Code exited with code 1" with zero tokens consumed.

### Discovered during live run

The `quant_modeler` agent in `examples/hedge_fund_full.yaml` had:
```yaml
sandbox:
  level: namespace
  network_enabled: false
  memory_limit_mb: 2048
```

This caused the `quant_model` task to fail instantly. Fixed by removing the sandbox config from the YAML (agents run without isolation).

### Additional issue: wrong workspace directory

The sandbox handle is created during adapter construction with `cwd = ws_root / "shared"`:
```python
# agentos/cli/workflow.py:273
workspace_path = ws_root / "shared"
sandbox_handle = sandbox_mgr.create(name, agent_cfg.sandbox, workspace_path)
```

But tasks now use per-task subdirectories (`ws_root / config.workspace / task_name`). The `NamespaceSandbox` ignores the workspace passed to `execute_task()` and uses its own `self._workspace` from construction time. This means sandboxed agents would run in the wrong directory.

### Additional issue: streaming bypassed

When a sandbox handle is set, the adapter skips the streaming code path:
```python
# agentos/adapters/tier2_claude_code.py:286-294
if self._sandbox is not None and self._run_subprocess is subprocess.run:
    result = self._sandbox.run(cmd, ...)  # No streaming, no log_fn
```

This means sandboxed agents lose real-time streaming output even when `log_fn` is configured.

## Fix Plan

### 1. Graceful fallback when `unshare` is unavailable

Check at sandbox creation time whether namespace isolation is possible:

```python
# In SandboxManager.create():
if config.level == SandboxLevel.NAMESPACE:
    # Test if unshare works (requires root or CAP_SYS_ADMIN)
    test = subprocess.run(
        ["unshare", "--pid", "--fork", "true"],
        capture_output=True, timeout=5,
    )
    if test.returncode != 0:
        logger.warning(
            f"Namespace sandbox unavailable for {agent_id} "
            f"(unshare requires root). Falling back to no isolation."
        )
        handle = NoopSandbox(workspace)
    else:
        handle = NamespaceSandbox(config, workspace)
```

### 2. Fix workspace directory mismatch

The sandbox handle should not hardcode `cwd` at construction time. Instead, pass `cwd` through from the adapter's `execute_task`:

```python
# SandboxHandle.run() should accept and forward cwd:
class NamespaceSandbox(SandboxHandle):
    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        unshare_flags = ["unshare", "--pid", "--mount", "--fork"]
        if not self._config.network_enabled:
            unshare_flags.append("--net")
        # Use cwd from kwargs if provided, otherwise fall back to construction workspace
        if "cwd" not in kwargs:
            kwargs["cwd"] = self._workspace
        return subprocess.run(unshare_flags + cmd, **kwargs)
```

And in `ClaudeCodeAdapter.execute_task`, pass `cwd`:

```python
result = self._sandbox.run(
    cmd,
    cwd=str(workspace),  # per-task workspace, not construction-time
    capture_output=True,
    text=True,
    timeout=self._timeout,
    env=env,
)
```

### 3. Support streaming inside sandboxes

Replace `subprocess.run` in sandbox handles with a mode that supports `Popen` for streaming:

```python
class SandboxHandle(ABC):
    @abstractmethod
    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a command inside the sandbox."""

    def wrap_command(self, cmd: list[str]) -> list[str]:
        """Return the command with sandbox wrapper prepended.

        Used by streaming code path which needs Popen, not run.
        """
        return cmd  # default: no wrapping
```

Then `NamespaceSandbox.wrap_command()` returns `["unshare", ...] + cmd`, and the adapter streaming path uses `sandbox.wrap_command(cmd)` instead of bare `cmd`.

### 4. Container sandbox: validate Docker availability

Same pattern as namespace — test at creation time:

```python
if config.level == SandboxLevel.CONTAINER:
    test = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
    if test.returncode != 0:
        logger.warning(f"Docker unavailable for {agent_id}. Falling back.")
        handle = NoopSandbox(workspace)
    else:
        handle = ContainerSandbox(config, workspace)
```

### 5. Memory limit enforcement for namespace level

Currently `memory_limit_mb` is stored but never enforced in `NamespaceSandbox`. Options:
- Use cgroups v2 (`cgcreate`, `cgset`, `cgexec`) — requires cgroup access
- Use `prlimit --as=` to set address space limits
- Use `systemd-run --scope -p MemoryMax=` — requires systemd

Simplest approach:
```python
# In NamespaceSandbox.run():
if self._config.memory_limit_mb > 0:
    unshare_flags = [
        "prlimit",
        f"--as={self._config.memory_limit_mb * 1024 * 1024}",
    ] + unshare_flags
```

## Files to Modify

| File | Change |
|------|--------|
| `agentos/security/sandbox.py` | Add fallback detection, `wrap_command()`, fix cwd handling |
| `agentos/adapters/tier2_claude_code.py` | Pass `cwd` to sandbox, use `wrap_command` for streaming |
| `agentos/cli/workflow.py` | Remove hardcoded `ws_root / "shared"`, pass per-task workspace |
| `tests/unit/test_sandbox.py` | Add tests for fallback, cwd forwarding, streaming compat |

## Workaround (Current)

Remove `sandbox:` from agent configs in YAML files. All agents run without isolation as standard subprocesses. This is the current state of `examples/hedge_fund_full.yaml`.
