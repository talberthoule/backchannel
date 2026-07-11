CREATE TABLE IF NOT EXISTS interest_subscribers (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  status TEXT NOT NULL DEFAULT 'interested'
    CHECK (status IN ('interested', 'invited', 'active', 'unsubscribed')),
  source TEXT NOT NULL DEFAULT 'homepage' CHECK (length(source) BETWEEN 1 AND 64),
  consent_version TEXT NOT NULL CHECK (length(consent_version) BETWEEN 1 AND 32),
  consent_at TEXT NOT NULL DEFAULT (datetime('now')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  invited_at TEXT,
  last_contacted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_interest_subscribers_status_created
  ON interest_subscribers(status, created_at);
