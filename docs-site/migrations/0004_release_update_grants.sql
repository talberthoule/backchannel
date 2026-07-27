CREATE TABLE release_update_grants (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE,
  version TEXT NOT NULL CHECK (
    length(version) BETWEEN 2 AND 32
    AND version GLOB 'v[0-9]*.[0-9]*.[0-9]*'
    AND substr(version, 2) NOT GLOB '*[^0-9.]*'
    AND length(version) - length(replace(version, '.', '')) = 2
  ),
  asset_id TEXT NOT NULL CHECK (asset_id IN (
    'windows-x64', 'macos-arm64', 'linux-x64'
  )),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

CREATE INDEX idx_release_update_grants_expires
  ON release_update_grants(expires_at);
