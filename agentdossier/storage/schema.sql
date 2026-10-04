-- AgentDossier instance database (SQLite). Applied idempotently at startup by storage.db.ensure_schema;
-- every table uses CREATE TABLE IF NOT EXISTS so a newer build can be started on an older file.
-- Additive changes go here; a destructive change needs a numbered migration (none yet).

-- operations
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT,
  status TEXT, trigger TEXT, resources INTEGER, report TEXT);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, event TEXT,
  channel TEXT, target TEXT, status TEXT, attempts INTEGER, detail TEXT);

-- decision workflow (FR-28, FR-34, FR-35)
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, resource_id TEXT NOT NULL, resource_name TEXT, title TEXT,
  stage TEXT NOT NULL, policy_id TEXT, required_roles TEXT NOT NULL, requested_by TEXT NOT NULL,
  owner TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS decision_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, at TEXT NOT NULL, user TEXT NOT NULL,
  from_stage TEXT, to_stage TEXT NOT NULL, note TEXT, verdict TEXT);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, at TEXT NOT NULL, user TEXT NOT NULL,
  role TEXT NOT NULL, verdict TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, parent_id INTEGER, at TEXT NOT NULL,
  user TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, title TEXT NOT NULL, assignee TEXT,
  due TEXT, status TEXT NOT NULL, created_by TEXT NOT NULL, created TEXT NOT NULL, completed TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, resource_id TEXT NOT NULL, decision_id INTEGER, at TEXT NOT NULL,
  user TEXT NOT NULL, kind TEXT NOT NULL, body TEXT, rating INTEGER, status TEXT NOT NULL, resolved_by TEXT,
  resolved TEXT);
CREATE INDEX IF NOT EXISTS ix_decisions_resource ON decisions(resource_id);
CREATE INDEX IF NOT EXISTS ix_feedback_resource ON feedback(resource_id);

-- SCIM 2.0 users (deprovisioning)
CREATE TABLE IF NOT EXISTS scim_users (id TEXT PRIMARY KEY, external_id TEXT, user_name TEXT UNIQUE,
  display_name TEXT, email TEXT, active INTEGER NOT NULL DEFAULT 1, created TEXT, updated TEXT, raw TEXT);
