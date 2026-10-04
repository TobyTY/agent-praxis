"""`praxis` command-line interface (Part K). Phase 0 commands only.

Every command accepts --json and then prints exactly one JSON object.
Exit codes: 0 ok, 1 failed check or error, 2 usage error (argparse).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from praxis import __version__, audit, config, forget, plugin, snapshot
from praxis.capture.ingest import ingest, spool_files
from praxis.db.conn import connect
from praxis.paths import Home, claude_config_dir


class Out:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json
        self.data: dict[str, Any] = {}

    def line(self, text: str = "") -> None:
        if not self.as_json:
            print(text)

    def set(self, **kw: Any) -> None:
        self.data.update(kw)

    def finish(self, code: int) -> int:
        if self.as_json:
            print(json.dumps({"ok": code == 0, **self.data}, ensure_ascii=False, default=str))
        return code


def _home(args: argparse.Namespace) -> Home:
    return Home.resolve(Path(args.home) if args.home else None)


def _require_init(home: Home, out: Out) -> bool:
    if home.key.exists() and home.config.exists():
        return True
    out.line(f"Praxis is not initialized at {home.root}. Run `praxis init` first.")
    out.set(error="not_initialized", home=str(home.root))
    return False


# ---------------------------------------------------------------- init


def cmd_init(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    home.ensure()
    created_config = False
    if not home.config.exists():
        home.config.write_text(config.dump(config.DEFAULTS), encoding="utf-8", newline="\n")
        created_config = True
    cfg = config.load(home.config)
    new_key = snapshot.generate_key(home)
    conn = connect(home.db)
    body = snapshot.compile_snapshot(home, conn, cfg)
    conn.close()
    audit.append(
        home.audit,
        "user",
        "init",
        str(home.root),
        {"new_key": new_key, "created_config": created_config, "version": __version__},
    )
    out.line(f"Praxis home: {home.root}")
    out.line(f"  config:   {'created' if created_config else 'kept'} {home.config}")
    out.line(f"  key:      {'generated' if new_key else 'kept'} {home.key}")
    out.line(f"  snapshot: compiled ({len(body['cards'])} cards)")
    out.set(home=str(home.root), created_config=created_config, new_key=new_key)

    plugin_dir = plugin.installed_plugin_dir()
    if plugin_dir:
        out.line(f"  plugin:   installed at {plugin_dir}")
    elif args.install_plugin:
        rc = _install_plugin(args.marketplace or plugin.MARKETPLACE_SOURCE, out)
        if rc:
            return out.finish(rc)
    else:
        out.line("")
        out.line("The Claude Code plugin is not installed. Install it with:")
        out.line(f"  claude plugin marketplace add {args.marketplace or plugin.MARKETPLACE_SOURCE}")
        out.line(f"  claude plugin install {plugin.PLUGIN_NAME}@{plugin.MARKETPLACE_NAME}")
        out.line("or rerun `praxis init --install-plugin`.")
    out.set(plugin_dir=str(plugin_dir) if plugin_dir else None)
    out.line("")
    return out.finish(_doctor(home, out))


def _install_plugin(source: str, out: Out) -> int:
    claude = shutil.which("claude")
    if not claude:
        out.line("`claude` is not on PATH; install Claude Code first.")
        out.set(error="claude_not_found")
        return 1
    for cmd in (
        [claude, "plugin", "marketplace", "add", source],
        [claude, "plugin", "install", f"{plugin.PLUGIN_NAME}@{plugin.MARKETPLACE_NAME}"],
    ):
        out.line("$ " + " ".join(cmd[1:]))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0 and "already" not in (proc.stdout + proc.stderr).lower():
            out.line(proc.stderr.strip() or proc.stdout.strip())
            out.set(error="plugin_install_failed", command=cmd[1:])
            return 1
    return 0


# ---------------------------------------------------------------- doctor


def _doctor(home: Home, out: Out) -> int:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        checks.append({"check": name, "ok": ok, "warn": warn and not ok, "detail": detail})
        mark = "ok  " if ok else ("warn" if warn else "FAIL")
        out.line(f"  [{mark}] {name}{': ' + detail if detail else ''}")

    out.line("praxis doctor")
    nv = plugin.node_version()
    node_ok = bool(nv) and int(nv.lstrip("v").split(".")[0]) >= 20 if nv else False
    check("node >= 20", node_ok, nv or "node not found on PATH")
    check("python >= 3.11", sys.version_info >= (3, 11), platform.python_version())
    check("praxis home", home.root.exists(), str(home.root))
    check("snapshot key", home.key.exists(), str(home.key))

    safe_mode = False
    try:
        snapshot.verify_file(home.snapshot, snapshot.read_key(home))
        check("snapshot HMAC", True, str(home.snapshot))
    except snapshot.SnapshotError as e:
        safe_mode = True
        check("snapshot HMAC", False, f"{e}; hooks run in safe mode. Run `praxis init` to recompile")

    res = audit.verify(home.audit)
    check("audit chain", res.ok, f"{res.entries} entries" if res.ok else f"{res.error} at line {res.line}")

    plugin_dir = plugin.find_plugin_dir()
    installed = plugin.installed_plugin_dir()
    check(
        "plugin installed",
        installed is not None,
        str(installed) if installed else "not in installed_plugins.json",
        warn=True,
    )
    hooks: list[dict[str, Any]] = []
    if plugin_dir:
        for r in plugin.self_test(plugin_dir):
            hooks.append(r.__dict__)
            check(f"hook {r.hook}", r.ok, f"{r.ms:.0f} ms" + (f"; {r.detail}" if r.detail else ""))
    else:
        check("hook self-test", False, "no plugin directory found", warn=True)

    # Phase 2 adds: static deny rules present, hooks present in the active settings.
    failed = [c for c in checks if not c["ok"] and not c["warn"]]
    out.set(checks=checks, hooks=hooks, safe_mode=safe_mode)
    out.line("")
    out.line("All checks passed." if not failed else f"{len(failed)} check(s) failed.")
    return 1 if failed else 0


def cmd_doctor(args: argparse.Namespace, out: Out) -> int:
    return out.finish(_doctor(_home(args), out))


# ---------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    if not _require_init(home, out):
        return out.finish(1)
    conn = connect(home.db)
    cards = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM cards GROUP BY status")}
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
        for t in ("projects", "sessions", "turns", "events", "signals")
    }
    queue = conn.execute("SELECT COUNT(*) FROM signals WHERE status = 'new'").fetchone()[0]
    today = datetime.now(UTC).date().isoformat()
    budget = conn.execute("SELECT runs, cost_usd FROM budgets WHERE day = ?", (today,)).fetchone()
    pending = 0
    for path in spool_files(home):
        rel = path.relative_to(home.root).as_posix()
        row = conn.execute("SELECT offset FROM spool_files WHERE path = ?", (rel,)).fetchone()
        pending += max(0, path.stat().st_size - (row[0] if row else 0))
    conn.close()
    try:
        snapshot.verify_file(home.snapshot, snapshot.read_key(home))
        safe_mode = False
    except snapshot.SnapshotError:
        safe_mode = True
    cfg = config.load(home.config)
    out.set(
        cards=cards,
        counts=counts,
        learning_queue=queue,
        budget={"day": today, "runs": budget[0] if budget else 0, "cost_usd": budget[1] if budget else 0.0},
        spool_bytes_pending=pending,
        safe_mode=safe_mode,
        guard_mode=cfg["guard"]["mode"],
    )
    out.line(f"Praxis {__version__} - home {home.root}")
    out.line(f"  cards:    {', '.join(f'{k} {v}' for k, v in sorted(cards.items())) or 'none'}")
    out.line(
        f"  traces:   {counts['projects']} projects, {counts['sessions']} sessions, "
        f"{counts['turns']} turns, {counts['events']} events"
    )
    out.line(
        f"  learning: {queue} signals queued - today {budget[0] if budget else 0} runs, "
        f"${(budget[1] if budget else 0.0):.2f}"
    )
    out.line(f"  spool:    {pending} bytes waiting for ingest")
    out.line(f"  guard:    mode {cfg['guard']['mode']}{' - SAFE MODE' if safe_mode else ''}")
    out.line("  taint:    per-session; reported by Guard from Phase 2")
    return out.finish(0)


# ---------------------------------------------------------------- ingest


def cmd_ingest(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    if not _require_init(home, out):
        # Called detached from SessionEnd before init: nothing to do, not an error.
        return out.finish(0 if args.quiet else 1)
    conn = connect(home.db)
    try:
        stats = ingest(home, conn)
    except TimeoutError:
        out.line("another ingest is running")
        out.set(skipped="locked")
        return out.finish(0)
    finally:
        conn.close()
    out.set(**stats.as_dict())
    if not args.quiet:
        out.line(
            f"ingested {stats.lines} lines from {stats.files} files: {stats.sessions} new sessions, "
            f"{stats.turns} turns, {stats.events} events, {stats.audits} audit entries, "
            f"{stats.malformed} malformed lines skipped"
        )
    return out.finish(0)


# ---------------------------------------------------------------- forget


def cmd_forget(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    if not _require_init(home, out):
        return out.finish(1)
    if not (args.session or args.project or args.all):
        out.line("choose one of --session ID, --project ID, --all")
        out.set(error="no_scope")
        return out.finish(2)
    if args.all and not args.yes:
        if args.json or not sys.stdin.isatty():
            out.set(error="confirmation_required", hint="pass --yes")
            out.line("refusing to delete all trace data without --yes")
            return out.finish(1)
        answer = input(f"Delete ALL Praxis trace data under {home.root}? Type 'forget' to confirm: ")
        if answer.strip() != "forget":
            out.line("aborted")
            return out.finish(1)
    conn = connect(home.db)
    try:
        ingest(home, conn)  # so project membership of un-ingested sessions is known
        if args.all:
            result, scope, target = forget.forget_all(home, conn), "all", None
        elif args.project:
            result, scope, target = forget.forget_project(home, conn, args.project), "project", args.project
        else:
            result, scope, target = (
                forget.forget_sessions(home, conn, [args.session]),
                "session",
                args.session,
            )
    finally:
        conn.close()
    forget.record(home, scope, target, result)
    out.set(scope=scope, target=target, **result.as_dict())
    out.line(
        f"forgot {result.sessions} session(s): {result.spool_files} spool files, "
        f"{result.blobs} blobs, rows {result.rows}"
    )
    return out.finish(0)


# ---------------------------------------------------------------- audit


def cmd_audit_verify(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    res = audit.verify(home.audit)
    out.set(entries=res.entries, error=res.error, line=res.line)
    out.line(
        f"audit chain OK: {res.entries} entries"
        if res.ok
        else f"audit chain BROKEN at line {res.line}: {res.error} ({res.entries} entries verified before it)"
    )
    return out.finish(0 if res.ok else 1)


# ---------------------------------------------------------------- uninstall


OWNER_MARKER = ".praxis-owned"


def cmd_uninstall(args: argparse.Namespace, out: Out) -> int:
    home = _home(args)
    purge = args.purge and home.root.exists()
    # Confirm before changing anything, so a refused purge leaves the install untouched.
    if purge and not args.yes:
        if args.json or not sys.stdin.isatty():
            out.set(error="confirmation_required", hint="pass --yes with --purge")
            out.line("refusing to purge data without --yes")
            return out.finish(1)
        answer = input(
            f"Remove Praxis and delete {home.root} with everything in it? Type 'purge' to confirm: "
        )
        if answer.strip() != "purge":
            out.line("aborted; nothing was changed")
            return out.finish(1)
    removed_skills = []
    skills_dir = claude_config_dir() / "skills"
    if skills_dir.exists():
        for d in skills_dir.glob("px-*"):
            if (d / OWNER_MARKER).exists():
                shutil.rmtree(d)
                removed_skills.append(d.name)
    out.line(f"removed {len(removed_skills)} materialized skill(s)")
    # Static deny rules are written from Phase 2; nothing to remove yet.
    plugin_removed = False
    if plugin.installed_plugin_dir() and shutil.which("claude"):
        claude = shutil.which("claude")
        assert claude
        proc = subprocess.run(
            [claude, "plugin", "uninstall", plugin.PLUGIN_NAME],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        plugin_removed = proc.returncode == 0
        out.line(
            "plugin uninstalled"
            if plugin_removed
            else f"could not uninstall the plugin: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    purged = False
    if purge:
        shutil.rmtree(home.root)
        purged = True
        out.line(f"deleted {home.root}")
    elif home.root.exists():
        audit.append(
            home.audit,
            "user",
            "uninstall",
            None,
            {"skills_removed": len(removed_skills), "plugin_removed": plugin_removed},
        )
        out.line(f"data kept at {home.root}; `praxis uninstall --purge` deletes it")
    out.set(skills_removed=removed_skills, plugin_removed=plugin_removed, purged=purged)
    return out.finish(0)


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print one JSON object")
    common.add_argument("--home", help="override $PRAXIS_HOME")

    p = argparse.ArgumentParser(prog="praxis", description="Verified procedural memory for coding agents.")
    p.add_argument("--version", action="version", version=f"praxis {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", parents=[common], help="create $PRAXIS_HOME, key, snapshot; check the plugin")
    s.add_argument("--install-plugin", action="store_true", help="run `claude plugin` to install the plugin")
    s.add_argument("--marketplace", help=f"marketplace source (default {plugin.MARKETPLACE_SOURCE})")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("doctor", parents=[common], help="check installation, snapshot, audit chain, hooks")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("status", parents=[common], help="cards, traces, queue, budget, safe mode")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("ingest", parents=[common], help="move spool lines into SQLite (idempotent)")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("forget", parents=[common], help="delete trace data")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--session")
    g.add_argument("--project")
    g.add_argument("--all", action="store_true")
    s.add_argument("--yes", action="store_true", help="skip the confirmation for --all")
    s.set_defaults(fn=cmd_forget)

    a = sub.add_parser("audit", help="audit log tools")
    asub = a.add_subparsers(dest="audit_command", required=True)
    s = asub.add_parser("verify", parents=[common], help="validate the hash chain")
    s.set_defaults(fn=cmd_audit_verify)

    s = sub.add_parser("uninstall", parents=[common], help="remove plugin and materialized skills")
    s.add_argument("--purge", action="store_true", help="also delete $PRAXIS_HOME")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_uninstall)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Out(getattr(args, "json", False))
    fn: Callable[[argparse.Namespace, Out], int] = args.fn
    try:
        return fn(args, out)
    except (config.ConfigError, snapshot.SnapshotError) as e:
        out.line(f"error: {e}")
        out.set(error=str(e))
        return out.finish(1)


if __name__ == "__main__":
    sys.exit(main())
