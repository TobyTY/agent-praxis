"""config.toml: defaults (Appendix B), loading and a minimal writer.

`tomllib` only reads TOML, so `dump` emits the flat two-level shape Praxis uses:
tables of scalars. Anything else is a programming error.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {"retain_days": 90},
    "router": {
        "enabled": True,
        "max_cards": 3,
        "top_k": 8,
        "min_score": 0.35,
        "resident_max": 8,
        "inject_char_cap": 2000,
    },
    "guard": {"mode": "ask", "taint_on_webfetch": False, "static_deny_rules": True},
    "learner": {
        "enabled": True,
        "model": "auto",
        "daily_run_budget": 40,
        "daily_cost_usd": 3.0,
        "min_trials_per_arm": 3,
        "max_trials_per_arm": 8,
        "promote_p_superior": 0.95,
        "promote_min_lift": 0.4,
        "futility_after": 5,
        "futility_p_superior": 0.6,
        "replay_max_turns": 8,
        "replay_concurrency": 2,
        "idle_only": True,
    },
    "privacy": {"store_assistant_text": "redacted-truncated", "assistant_excerpt_chars": 1500},
}

GUARD_MODES = ("minimal", "audit", "ask", "strict")
ASSISTANT_TEXT_MODES = ("none", "redacted-truncated")


class ConfigError(ValueError):
    pass


def load(path: Path) -> dict[str, dict[str, Any]]:
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        with path.open("rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if section not in cfg:
                raise ConfigError(f"unknown config section [{section}]")
            if not isinstance(values, dict):
                raise ConfigError(f"[{section}] must be a table")
            for key, value in values.items():
                if key not in cfg[section]:
                    raise ConfigError(f"unknown config key {section}.{key}")
                expected = type(DEFAULTS[section][key])
                if expected is float and isinstance(value, int) and not isinstance(value, bool):
                    value = float(value)
                if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
                    raise ConfigError(f"{section}.{key} must be {expected.__name__}")
                cfg[section][key] = value
    _validate(cfg)
    return cfg


def _validate(cfg: dict[str, dict[str, Any]]) -> None:
    if cfg["guard"]["mode"] not in GUARD_MODES:
        raise ConfigError(f"guard.mode must be one of {', '.join(GUARD_MODES)}")
    if cfg["privacy"]["store_assistant_text"] not in ASSISTANT_TEXT_MODES:
        raise ConfigError(f"privacy.store_assistant_text must be one of {', '.join(ASSISTANT_TEXT_MODES)}")
    if cfg["general"]["retain_days"] < 1:
        raise ConfigError("general.retain_days must be >= 1")


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise ConfigError(f"cannot write {type(value).__name__} to TOML")


def dump(cfg: dict[str, dict[str, Any]]) -> str:
    out = ["# Praxis configuration. Defaults: docs/MASTER_PROMPT.md Appendix B.", ""]
    for section, values in cfg.items():
        out.append(f"[{section}]")
        out.extend(f"{key} = {_scalar(value)}" for key, value in values.items())
        out.append("")
    return "\n".join(out)
