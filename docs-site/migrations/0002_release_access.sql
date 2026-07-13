ALTER TABLE interest_subscribers ADD COLUMN release_decision TEXT NOT NULL DEFAULT 'pending'
  CHECK (release_decision IN ('pending', 'approved', 'rejected'));
ALTER TABLE interest_subscribers ADD COLUMN release_reviewed_at TEXT;

CREATE TABLE release_accounts (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  password_iterations INTEGER NOT NULL DEFAULT 600000 CHECK (password_iterations = 600000),
  must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0, 1)),
  password_expires_at TEXT,
  include_latest INTEGER NOT NULL DEFAULT 1 CHECK (include_latest IN (0, 1)),
  approved_at TEXT NOT NULL DEFAULT (datetime('now')),
  password_changed_at TEXT,
  revoked_at TEXT,
  FOREIGN KEY (email) REFERENCES interest_subscribers(email)
);

CREATE TABLE release_account_versions (
  email TEXT NOT NULL,
  version TEXT NOT NULL CHECK (length(version) BETWEEN 2 AND 32),
  granted_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (email, version),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

CREATE TABLE release_sessions (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  password_change_only INTEGER NOT NULL CHECK (password_change_only IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL,
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

CREATE TABLE release_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  action TEXT NOT NULL,
  version TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_release_sessions_email_expires
  ON release_sessions(email, expires_at);
CREATE INDEX idx_release_access_events_email_created
  ON release_access_events(email, created_at);
CREATE INDEX idx_release_account_versions_version
  ON release_account_versions(version);
