"""Locate the Praxis Claude Code plugin and self-test its hooks (used by init and doctor)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from praxis.paths import claude_config_dir

PLUGIN_NAME = "praxis"
MARKETPLACE_NAME = "agent-praxis"
MARKETPLACE_SOURCE = "TobyTY/agent-praxis"
HOOK_FILES = ["session-start.mjs", "route.mjs", "capture.mjs", "session-end.mjs"]


def installed_plugin_dir() -> Path | None:
    """Install path from Claude Code's installed_plugins.json, if Praxis is installed."""
    registry = claude_config_dir() / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for key, installs in (data.get("plugins") or {}).items():
        if key.split("@", 1)[0] == PLUGIN_NAME and installs:
            path = Path(installs[0].get("installPath", ""))
            if (path / "hooks" / "hooks.json").exists():
                return path
    return None


def checkout_plugin_dir() -> Path | None:
    """The plugin directory of a source checkout (core/praxis/plugin.py -> repo/plugin)."""
    candidate = Path(__file__).resolve().parents[2] / "plugin"
    return candidate if (candidate / "hooks" / "hooks.json").exists() else None


def find_plugin_dir() -> Path | None:
    env = os.environ.get("PRAXIS_PLUGIN_DIR")
    if env and (Path(env) / "hooks" / "hooks.json").exists():
        return Path(env)
    return installed_plugin_dir() or checkout_plugin_dir()


def node_version() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


@dataclass
class HookCheck:
    hook: str
    ok: bool
    exit_code: int | None
    ms: float
    detail: str = ""


_SAMPLE_INPUTS: dict[str, tuple[list[str], dict[str, Any]]] = {
    "session-start.mjs": ([], {"hook_event_name": "SessionStart", "source": "startup"}),
    "route.mjs": ([], {"hook_event_name": "UserPromptSubmit", "prompt": "praxis doctor self-test prompt"}),
    "capture.mjs": (
        ["tool_ok"],
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo ok"},
            "tool_response": {"stdout": "ok", "exitCode": 0},
            "tool_use_id": "toolu_selftest",
        },
    ),
    "session-end.mjs": ([], {"hook_event_name": "SessionEnd", "reason": "other"}),
}


def self_test(plugin_dir: Path, runs: int = 3) -> list[HookCheck]:
    """Run every hook against a throwaway PRAXIS_HOME. Never touches the real home."""
    node = shutil.which("node")
    results: list[HookCheck] = []
    if not node:
        return [HookCheck(h, False, None, 0.0, "node not found on PATH") for h in HOOK_FILES]
    with tempfile.TemporaryDirectory(prefix="praxis-doctor-") as tmp:
        env = {**os.environ, "PRAXIS_HOME": tmp, "PRAXIS_NO_SPAWN": "1"}
        env.pop("PRAXIS_MODE", None)
        for hook in HOOK_FILES:
            script = plugin_dir / "dist" / hook
            if not script.exists():
                results.append(HookCheck(hook, False, None, 0.0, "missing from dist/"))
                continue
            args, payload = _SAMPLE_INPUTS[hook]
            stdin = json.dumps({"session_id": "doctor-selftest", "cwd": tmp, **payload})
            times, code, detail = [], None, ""
            for _ in range(runs):
                start = time.perf_counter()
                proc = subprocess.run(
                    [node, str(script), *args],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                    check=False,
                )
                times.append((time.perf_counter() - start) * 1000)
                code = proc.returncode
                if proc.returncode != 0:
                    detail = proc.stderr.strip()[:200]
                    break
                out = proc.stdout.strip()
                if out:
                    try:
                        json.loads(out)
                    except json.JSONDecodeError:
                        detail = "stdout is not a single JSON object"
                        code = -1
                        break
            times.sort()
            results.append(HookCheck(hook, code == 0, code, times[len(times) // 2], detail))
    return results
