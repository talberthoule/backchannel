CREATE TABLE release_access_policies (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  include_latest INTEGER NOT NULL DEFAULT 1
    CHECK (include_latest IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

INSERT INTO release_access_policies (email, include_latest, updated_at)
SELECT email, include_latest, approved_at FROM release_accounts;
