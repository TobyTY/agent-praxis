# Hook contracts

Facts about the host that Praxis depends on, recorded from the official docs and checked
against the installed CLI. Every hook, plugin and headless call in this repository must
agree with this file. When the host changes, update this file first, then the code.

- **Verified against:** Claude Code `2.1.248` (`claude --version`), docs fetched 2026-10-04
  from `https://code.claude.com/docs/en/*.md` (hooks, hooks-guide, skills, plugins,
  plugins-reference, plugin-marketplaces, settings, permissions, headless, cli-reference,
  tools-reference, env-vars, sub-agents) and `https://agentskills.io/specification`.
- **Docs are ahead of the installed CLI.** The docs describe features up to at least
  v2.1.269. Where a feature needs a newer version than 2.1.248, it is marked below and the
  code treats it as optional.

## 1. Configuration and handlers

| Fact | Value | Source |
|---|---|---|
| Plugin hook file | `<plugin>/hooks/hooks.json`, top-level `{"hooks": {...}}` wrapper | plugins-reference |
| Plugin manifest | `<plugin>/.claude-plugin/plugin.json`; `name` is the only required key; everything else lives at the plugin root, not inside `.claude-plugin/` | plugins-reference |
| Marketplace manifest | `<root>/.claude-plugin/marketplace.json` with `name`, `owner`, `plugins[]` (`name`, `source` relative to the marketplace root) | plugin-marketplaces |
| Exec form | `"command": "node", "args": [...]` spawns directly with no shell. `${CLAUDE_PLUGIN_ROOT}` is substituted into each arg as a plain string | hooks §Exec form |
| Windows exec form | `command` must resolve to a real executable (`node.exe`); `.cmd`/`.bat` shims fail | hooks §Exec form |
| Env exported to hooks | `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` | hooks §Exec form |
| Matcher semantics | Only `[A-Za-z0-9_\- ,|]` → exact names; anything else → **unanchored** JS regex. Anchor with `^…$` | hooks §Matcher patterns |
| Handlers run in parallel | All matching handlers for one event run concurrently | hooks §Hook handler fields |
| Hooks in subagents | Tool events fire inside subagents; input carries `agent_id`, `agent_type` | hooks §Hook locations |
| `if` field | Best effort; "use the permission system rather than a hook to enforce a hard allow or deny" | hooks §Common fields |
| `disableAllHooks` | Setting in any settings file; `--settings '{"disableAllHooks": true}'` overrides for one run | hooks §Disable or remove hooks |

## 2. Timeouts

| Event / type | Default timeout | Notes |
|---|---|---|
| command (most events) | 600 s | |
| `UserPromptSubmit`, `PreModelSwitch`, `PostModelSwitch` | 30 s | Timed-out UserPromptSubmit output is **discarded**; prompt proceeds without context |
| `SessionEnd` | 1.5 s shared budget | Plugin-provided `timeout` values **do not** raise the budget. Only user settings or `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` do |
| `async: true` command hooks | not enforced | Async output fields (`decision`, `permissionDecision`, `continue`) have no effect |
| Timed-out PreToolUse command hook | **does not block**; normal permission flow continues | hooks §Timeouts |

Consequence for Praxis: `session-end.mjs` must spool and spawn the detached ingest in well
under 1.5 s, and a plugin cannot buy more time. Guard cannot rely on its own timeout to
block (Part F.1 #9 residual risk is real).

## 3. Exit codes and output

- Exit 0: stdout parsed as JSON when it starts with `{` and ends with `}`; otherwise plain
  text. Plain text becomes Claude context only for `UserPromptSubmit`,
  `UserPromptExpansion`, `SessionStart`, `PostModelSwitch`.
- From v2.1.248, stdout that looks like JSON but fails to parse is a non-blocking error and
  is **not** added as context. Praxis prints either nothing or exactly one valid object.
- Exit 2: blocks on events that can block (PreToolUse, UserPromptSubmit,
  UserPromptExpansion, Stop, ConfigChange except `policy_settings`, …). Stderr becomes the
  reason. A JSON `allow` cannot override exit 2.
- Exit 1 or any other code: non-blocking error; the action proceeds. **Never use exit 1 to
  block.**
- Stderr on exit 0 goes to the debug log only.
- `additionalContext`, `systemMessage`, `initialUserMessage` and plain stdout are each
  capped at **10,000 chars**; overflow is written to a file with a 2,000-char preview that
  Claude is not asked to read. Praxis caps injections at 2,000 chars.
- Docs advise factual, not imperative, `additionalContext`; imperative out-of-band text can
  trip prompt-injection defenses.

## 4. Per-event contracts used by Praxis

### Common input
`session_id`, `prompt_id` (v2.1.196+, absent before first prompt), `transcript_path`, `cwd`,
`scratchpad_dir` (v2.1.257+, optional), `permission_mode` (not on every event),
`hook_event_name`, optional `agent_id`/`agent_type`, optional `effort.level`.
There is no `$CLAUDE_MODEL` env var.

### SessionStart
- Only `command` and `mcp_tool` handlers are supported.
- `model` was absent in every `claude -p` run observed on 2.1.248.
- Input: `source` ∈ `startup | resume | clear | compact | fork` (fork from v2.1.214; earlier
  reported `resume`); optional `model` (may be absent, e.g. after `/clear`); optional
  `agent_type`, `session_title`; on resume/fork with history (v2.1.251+):
  `seconds_since_last_response`, `context_tokens`, `prompt_cache_likely_expired`,
  `estimated_cache_write_usd`.
- Output: `hookSpecificOutput.{additionalContext, initialUserMessage, sessionTitle,
  watchPaths, reloadSkills}`. `reloadSkills: true` re-scans skill directories after the
  hooks finish, so skills written by the hook are usable from the first prompt.
- Runs in the background at launch; Claude's first response waits for it.

### UserPromptSubmit
- Fires on typed prompts **and** on scheduled tasks, `/loop` iterations, background subagent
  reports and cross-session messages. Routing must tolerate non-human prompts.
- Input: `prompt` (pasted content expanded, possibly wrapped in `<pasted_content …>` lines),
  optional `session_title`.
- Output: `decision: "block"` + `reason`, or `hookSpecificOutput.{additionalContext,
  sessionTitle, suppressOriginalPrompt}`.

### UserPromptExpansion
- Fires when a typed `/command` expands. Covers the path PreToolUse on `Skill` misses.
- Input: `expansion_type` (`slash_command | mcp_prompt`), `command_name`, `command_args`,
  `command_source`, `prompt`.

### PreToolUse
- Input: `tool_name`, `tool_input`, `tool_use_id`; MCP tools also carry
  `mcp_server.{name, source}`.
- `Write`, `Edit`, `Read` `file_path` is always absolute, `~` and relative paths are
  pre-expanded; **on Windows it arrives with backslashes**.
- `Bash` / `PowerShell` `tool_input.command`. On Windows without Git Bash only PowerShell
  exists, so shell matchers must include both.
- `Skill` tool input: `{"skill": "<plugin:>name", "args"?: "..."}` (observed in local
  transcripts; the tools reference does not document the schema).
- Output: `hookSpecificOutput.{permissionDecision: allow|deny|ask|defer,
  permissionDecisionReason, updatedInput, additionalContext}`. Precedence across hooks:
  `deny > defer > ask > allow`. `defer` is honored only in `-p` mode.
- Deny reason is shown to Claude; ask reason is shown to the user with a `[plugin:<name>]`
  label. A hook `ask` forces a prompt even in auto mode (v2.1.211+).

### PostToolUse / PostToolUseFailure
- PostToolUse input: `tool_input`, `tool_response`, `tool_use_id`, optional `duration_ms`.
- PostToolUseFailure input: `tool_input`, `tool_use_id`, `error` (string, first line
  `Exit code N` for shells, may be middle-truncated), optional `is_interrupt`, `duration_ms`.
  Does not fire for permission denials or validation rejections.
- `tool_response.bashEditDiff` (`changedFiles`, `files`, `moreFiles`, `unavailable`,
  `skipped`, `shared`) requires **v2.1.269+** and is public beta. Not available on 2.1.248.
  Capture stores it when present; test synthesis marks fidelity `approximate` otherwise.

### Stop
- Input: `stop_hook_active`, `last_assistant_message`, `background_tasks[]`,
  `session_crons[]`. Use `last_assistant_message`, not the transcript file.

### ConfigChange
- Matcher on `source`: `user_settings | project_settings | local_settings |
  policy_settings | skills`.
- Input: `source`, optional `file_path`. **No diff is provided.** Self-protection must
  compare against a cached copy of the settings file.
- Block with exit 2 or `decision: "block"`. `policy_settings` cannot be blocked. A blocked
  change shows no message to the user or Claude; only the debug log records it.

### PostModelSwitch (v2.1.251+)
- Input: `from_model`, `to_model`, `requested_model`, `source` (adds `auto`, `resume`),
  cost fields.
- **Not registered in `hooks.json` yet.** `claude plugin validate` on 2.1.248 rejects the
  key (`hooks.PostModelSwitch: Invalid key in record`), so a manifest with it fails to load
  on that version. `capture.mjs` already handles `model_switch`; the hook entry returns when
  the minimum supported version reaches 2.1.251 (ADR 0006). Until then the Learner compares
  SessionStart `model` with the evidence model.

### SessionEnd
- Input: `reason` ∈ `clear | resume | logout | prompt_input_exit | other`.
- 1.5 s shared budget (see §2). Output fields are discarded.
- **Observed on 2.1.248, Windows, `claude -p`:** SessionEnd is not delivered reliably. A
  probe plugin with only a SessionEnd hook fired 2 of 2 runs and received stdin at 3 ms with
  EOF at 4 ms, then was killed at about 1.6 s. With the Praxis plugin loaded (which also has
  async PostToolUse/Stop hooks) SessionEnd fired in 2 of 6 runs, and never when
  `--debug-file` was set (the debug log has no SessionEnd entry at all). Praxis therefore
  never depends on SessionEnd: ingest is idempotent and runs on any `praxis` command, and
  `sessions.ended_at` may stay empty. Interactive exits are expected to fire it; the
  Learner (Phase 1) treats a session idle for longer than its window as ended.
- When it does fire, the detached `praxis ingest` it spawns survives Claude Code's exit on
  Windows: in the recorded run (`docs/evidence/phase0-e2e-capture.json`) the follow-up
  ingest found 0 new lines because the detached one had already ingested all of them.

## 5. Skills

| Fact | Value |
|---|---|
| Personal skills dir | `~/.claude/skills/<name>/SKILL.md` (respects `CLAUDE_CONFIG_DIR`) |
| Project skills dir | `.claude/skills/<name>/SKILL.md` |
| Frontmatter `metadata` | Agent Skills spec: map of **string → string**. Claude Code ignores it and drops non-map values |
| Listing budget | 1% of context window, fallback 8,000 chars; `skillListingBudgetFraction` setting or `SLASH_COMMAND_TOOL_CHAR_BUDGET` env var. Overflowing descriptions are dropped; names stay |
| Skill-scoped hooks | Skill frontmatter can declare hooks that stay registered for the rest of the session once invoked. Relevant to the Guard threat model (T1) |

Decision: `metadata` allows only string values, so the structured sidecar `praxis.json`
stays (Part E.1). Frontmatter carries only `metadata.praxis-id`.

## 6. Permissions (static deny rules, Phase 2)

- Absolute paths in rules use `//` (`Edit(//Users/alice/.praxis/**)`); a single leading `/`
  is relative to the settings source. `~/` is home-relative.
- On Windows, paths normalize to POSIX before matching: `C:\Users\a` → `/c/Users/a`, so a
  rule reads `Edit(//c/Users/a/.praxis/**)`.
- Deny rules also match the symlink target.

## 7. Headless (`claude -p`) for internal calls and replays

| Need | Flag / variable |
|---|---|
| Isolated config | `CLAUDE_CONFIG_DIR=<dir>` (cannot be set from project/local settings) |
| Skip auto-discovery | `--bare` skips hooks, skills, plugins, MCP, CLAUDE.md; `--plugin-dir`, `--settings`, `--append-system-prompt[-file]`, `--add-dir` still apply |
| Load the plugin for one run | `--plugin-dir <path>` (repeatable) |
| Appended system context | `--append-system-prompt` / `--append-system-prompt-file` |
| Turn cap | `--max-turns N` (print mode; exits with an error at the cap) |
| Spend cap | `--max-budget-usd X` (print mode) |
| Tool restriction | `--tools "Bash,Edit,Read"` (availability) and `--disallowedTools` (deny rules) |
| Output | `--output-format json | stream-json`; JSON result includes `total_cost_usd` and per-model cost |
| No transcript | `--no-session-persistence` |
| Setting sources | `--setting-sources user,project,local` |

## 8. [verify] items from the master prompt

| Item | Status |
|---|---|
| PreToolUse decisions allow/deny/ask/defer via `permissionDecision`; exit 2 blocks; exit 1 does not | Confirmed (§3, §4) |
| Timed-out PreToolUse command hook does not block | Confirmed (§2) |
| `additionalContext` cap 10,000; plain stdout is context on UserPromptSubmit/SessionStart | Confirmed (§3) |
| UserPromptSubmit default timeout 30 s, output discarded on timeout | Confirmed (§2) |
| SessionStart `reloadSkills`; `source` values | Confirmed (§4) |
| Hooks fire in subagents with `agent_id`/`agent_type` | Confirmed (§1) |
| UserPromptExpansion fires for typed commands; PreToolUse `Skill` only on tool call | Confirmed (§4) |
| Windows backslash paths; exec form needs a real executable | Confirmed (§1, §4) |
| `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`; async hooks don't block | Confirmed (§1, §2) |
| ConfigChange can block user/project/local with exit 2; which fields describe the change | Confirmed; **no diff field**, only `source` + `file_path` (§4) |
| Skill-listing budget names and defaults | Confirmed (§5) |
| Isolated config dir; headless flags; cost fields | Confirmed (§7). Installing the plugin into an isolated config: use `--plugin-dir` per run instead of installing |
| `bashEditDiff` | Exists from v2.1.269, beta; optional in code |
| PostModelSwitch registration | Rejected by the 2.1.248 plugin validator; deferred (ADR 0006) |
| `mcp_server.source` on PreToolUse | Documented; version not stated. Optional in code |
| Skill tool input field name | `skill` (observed, undocumented) |
| Agent Skills `metadata` structure | String → string map only; sidecar kept |
| Detached spawn on Windows survives the SessionEnd budget | Confirmed on Windows (§4 SessionEnd); SessionEnd itself is unreliable under `-p` |
| Permission-rule syntax for static deny rules | Confirmed (§6); implemented in Phase 2 |
