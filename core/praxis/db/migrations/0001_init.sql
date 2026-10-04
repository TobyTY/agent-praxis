-- Schema from docs/MASTER_PROMPT.md Part E.2. Connection pragmas (WAL, foreign keys)
-- are set in praxis/db/conn.py because journal_mode cannot change inside a transaction.

CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE TABLE projects (
  id TEXT PRIMARY KEY,                    -- prj_<hash(canonical root + git remote)>
  root_hash TEXT NOT NULL,                -- raw absolute paths never appear in exports
  stack_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  started_at TEXT NOT NULL, ended_at TEXT, source TEXT,
  model TEXT, cc_version TEXT, git_head TEXT, dirty_patch_blob TEXT
);

CREATE TABLE turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  idx INTEGER NOT NULL, prompt_id TEXT,
  user_text TEXT,                         -- redacted
  assistant_excerpt TEXT,                 -- redacted, truncated
  injected_cards_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE (session_id, idx)
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_idx INTEGER, ts TEXT NOT NULL,
  kind TEXT NOT NULL,                     -- tool_ok | tool_fail | guard | activation | model_switch | ...
  tool_name TEXT, tool_use_id TEXT, agent_id TEXT,
  input_json TEXT, outcome_json TEXT,     -- redacted; large payloads live in blobs
  blob TEXT
);
CREATE INDEX events_by_session ON events (session_id, turn_idx);

CREATE TABLE signals (
  id TEXT PRIMARY KEY, type TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_from INTEGER, turn_to INTEGER,
  event_ids_json TEXT NOT NULL, cluster_id TEXT,
  confidence REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',     -- new | distilled | discarded
  created_at TEXT NOT NULL
);

CREATE TABLE cards (
  id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL, tier TEXT NOT NULL, origin TEXT NOT NULL,
  current_version INTEGER NOT NULL, scope_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE card_versions (
  card_id TEXT NOT NULL REFERENCES cards(id), version INTEGER NOT NULL,
  content_md TEXT NOT NULL, description TEXT NOT NULL,
  triggers_json TEXT NOT NULL, synthetic_queries_json TEXT NOT NULL DEFAULT '[]',
  capabilities_json TEXT NOT NULL, capabilities_approved INTEGER NOT NULL DEFAULT 0,
  provenance_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (card_id, version)
);

CREATE TABLE edges (
  src TEXT NOT NULL REFERENCES cards(id), dst TEXT NOT NULL REFERENCES cards(id),
  type TEXT NOT NULL CHECK (type IN ('conflicts','supersedes','requires','specializes','redundant')),
  confidence REAL NOT NULL, method TEXT NOT NULL, evidence_ref TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, type)
);

CREATE TABLE test_cases (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('targeted','regression')),
  signal_id TEXT REFERENCES signals(id), project_id TEXT,
  repo_commit TEXT NOT NULL, state_blob TEXT NOT NULL,
  capsule_md TEXT NOT NULL, trigger_prompt TEXT NOT NULL,
  assertions_json TEXT NOT NULL,
  fidelity TEXT NOT NULL CHECK (fidelity IN ('exact','approximate'))
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  test_case_id TEXT NOT NULL REFERENCES test_cases(id),
  card_id TEXT, card_version INTEGER,
  arm TEXT NOT NULL CHECK (arm IN ('A','B')), trial INTEGER NOT NULL,
  model TEXT, cc_version TEXT, started_at TEXT NOT NULL, duration_ms INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL,
  valid INTEGER NOT NULL DEFAULT 1,       -- 0 if grader/test files were tampered with
  passed INTEGER NOT NULL, assertion_results_json TEXT NOT NULL, trace_blob TEXT NOT NULL
);

CREATE TABLE evidence (
  card_id TEXT NOT NULL, card_version INTEGER NOT NULL, model TEXT NOT NULL,
  n_a INTEGER, pass_a INTEGER, n_b INTEGER, pass_b INTEGER,
  p_superior REAL, lift REAL, regressions_ok INTEGER,
  verdict TEXT NOT NULL, bundle_path TEXT NOT NULL, bundle_sha256 TEXT NOT NULL,
  stale INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  PRIMARY KEY (card_id, card_version, model)
);

CREATE TABLE usage (
  card_id TEXT NOT NULL, session_id TEXT NOT NULL, turn_idx INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('clean','negative_signal','unknown')),
  PRIMARY KEY (card_id, session_id, turn_idx)
);

CREATE TABLE budgets (day TEXT PRIMARY KEY, runs INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0);

-- Not in Part E.2: ingest bookkeeping. One row per spool file; offset is the byte
-- position after the last complete line ingested, which makes ingest idempotent.
CREATE TABLE spool_files (
  path TEXT PRIMARY KEY,                  -- relative to $PRAXIS_HOME, forward slashes
  offset INTEGER NOT NULL,
  malformed INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
