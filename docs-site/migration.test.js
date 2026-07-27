import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

const migration1 = readFileSync(new URL('./migrations/0001_interest_subscribers.sql', import.meta.url), 'utf8');
const migration2 = readFileSync(new URL('./migrations/0002_release_access.sql', import.meta.url), 'utf8');
const migration3 = readFileSync(
  new URL('./migrations/0003_release_access_policies.sql', import.meta.url),
  'utf8',
);
const migration4 = readFileSync(
  new URL('./migrations/0004_release_update_grants.sql', import.meta.url),
  'utf8',
);

function databaseThrough2() {
  const db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys = ON');
  db.exec(migration1);
  db.exec(migration2);
  return db;
}

function database() {
  const db = databaseThrough2();
  db.exec(migration3);
  db.exec(migration4);
  return db;
}

function insertInterest(db, email = 'person@example.com') {
  db.prepare(`
    INSERT INTO interest_subscribers (email, consent_version)
    VALUES (?, '2026-07-12')
  `).run(email);
}

function insertAccount(db, email = 'person@example.com') {
  db.prepare(`
    INSERT INTO release_accounts (email, state, password_hash, password_salt)
    VALUES (?, 'active', 'hash', 'salt')
  `).run(email);
}

test('migration adds decision fields and the exact release tables', () => {
  const db = database();
  try {
    const interestColumns = db.prepare('PRAGMA table_info(interest_subscribers)').all();
    assert.equal(interestColumns.find(({ name }) => name === 'release_decision').dflt_value, "'pending'");
    assert.equal(interestColumns.find(({ name }) => name === 'release_decision').notnull, 1);
    assert.equal(interestColumns.find(({ name }) => name === 'release_reviewed_at').notnull, 0);

    const expected = {
      release_accounts: [
        'email', 'state', 'password_hash', 'password_salt', 'password_iterations',
        'must_change_password', 'password_expires_at', 'include_latest', 'approved_at',
        'password_changed_at', 'revoked_at',
      ],
      release_account_versions: ['email', 'version', 'granted_at'],
      release_sessions: [
        'token_hash', 'email', 'password_change_only', 'created_at', 'expires_at',
      ],
      release_access_events: ['id', 'email', 'action', 'version', 'created_at'],
    };
    for (const [tableName, columnNames] of Object.entries(expected)) {
      assert.deepEqual(
        db.prepare(`PRAGMA table_info(${tableName})`).all().map(({ name }) => name),
        columnNames,
      );
    }
  } finally {
    db.close();
  }
});

test('decision and account constraints enforce the approval invariant', () => {
  const db = database();
  try {
    insertInterest(db, 'Person@Example.com');
    assert.throws(
      () => db.exec("UPDATE interest_subscribers SET release_decision = 'maybe'"),
      /CHECK constraint failed/,
    );
    assert.throws(() => insertAccount(db, 'missing@example.com'), /FOREIGN KEY constraint failed/);

    insertAccount(db, 'person@example.com');
    assert.throws(() => insertAccount(db, 'PERSON@example.com'), /UNIQUE constraint failed/);
    const account = db.prepare('SELECT * FROM release_accounts').get();
    assert.equal(account.email, 'person@example.com');
    assert.equal(account.password_iterations, 600_000);
    assert.equal(account.must_change_password, 1);
    assert.equal(account.include_latest, 1);
    assert.ok(account.approved_at);

    for (const [column, value] of [
      ['state', "'disabled'"],
      ['password_iterations', '1'],
      ['must_change_password', '2'],
      ['include_latest', '-1'],
    ]) {
      assert.throws(
        () => db.exec(`UPDATE release_accounts SET ${column} = ${value}`),
        /CHECK constraint failed/,
      );
    }
    assert.throws(
      () => db.exec("DELETE FROM interest_subscribers WHERE email = 'person@example.com'"),
      /FOREIGN KEY constraint failed/,
    );
  } finally {
    db.close();
  }
});

test('version and session constraints reject malformed or orphaned rows', () => {
  const db = database();
  try {
    insertInterest(db);
    insertAccount(db);
    db.exec(`
      INSERT INTO release_account_versions (email, version) VALUES ('person@example.com', 'v1.0.0');
      INSERT INTO release_sessions (token_hash, email, password_change_only, expires_at)
        VALUES ('token', 'person@example.com', 1, datetime('now', '+30 minutes'));
    `);
    assert.throws(
      () => db.exec("INSERT INTO release_account_versions (email, version) VALUES ('person@example.com', 'v')"),
      /CHECK constraint failed/,
    );
    assert.throws(
      () => db.exec(`INSERT INTO release_account_versions (email, version) VALUES ('person@example.com', '${'v'.repeat(33)}')`),
      /CHECK constraint failed/,
    );
    assert.throws(
      () => db.exec("INSERT INTO release_account_versions (email, version) VALUES ('person@example.com', 'v1.0.0')"),
      /UNIQUE constraint failed/,
    );
    assert.throws(
      () => db.exec("INSERT INTO release_account_versions (email, version) VALUES ('missing@example.com', 'v1.0.0')"),
      /FOREIGN KEY constraint failed/,
    );
    assert.throws(
      () => db.exec("INSERT INTO release_sessions (token_hash, email, password_change_only, expires_at) VALUES ('bad-flag', 'person@example.com', 2, datetime('now'))"),
      /CHECK constraint failed/,
    );
    assert.throws(
      () => db.exec("INSERT INTO release_sessions (token_hash, email, password_change_only, expires_at) VALUES ('orphan', 'missing@example.com', 0, datetime('now'))"),
      /FOREIGN KEY constraint failed/,
    );
    assert.throws(
      () => db.exec("INSERT INTO release_sessions (token_hash, email, password_change_only, expires_at) VALUES ('token', 'person@example.com', 0, datetime('now'))"),
      /UNIQUE constraint failed/,
    );
  } finally {
    db.close();
  }
});

test('account deletion cascades grants and sessions but retains audit events', () => {
  const db = database();
  try {
    insertInterest(db);
    insertAccount(db);
    db.exec(`
      INSERT INTO release_account_versions (email, version) VALUES ('person@example.com', 'v1.0.0');
      INSERT INTO release_sessions (token_hash, email, password_change_only, expires_at)
        VALUES ('token', 'person@example.com', 0, datetime('now', '+7 days'));
      INSERT INTO release_access_events (email, action, version)
        VALUES ('person@example.com', 'download_start', 'v1.0.0');
      DELETE FROM release_accounts WHERE email = 'person@example.com';
    `);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_account_versions').get().count, 0);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_sessions').get().count, 0);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_access_events').get().count, 1);
  } finally {
    db.close();
  }
});

test('migration 0003 backfills release access policies without changing explicit grants', () => {
  const db = databaseThrough2();
  try {
    insertInterest(db, 'latest@example.com');
    insertAccount(db, 'latest@example.com');
    insertInterest(db, 'pinned@example.com');
    db.prepare(`
      INSERT INTO release_accounts
        (email, state, password_hash, password_salt, include_latest, approved_at)
      VALUES (?, 'active', 'hash', 'salt', 0, '2026-07-13 12:00:00')
    `).run('pinned@example.com');
    db.prepare(`
      INSERT INTO release_account_versions (email, version)
      VALUES ('pinned@example.com', 'v0.2.1')
    `).run();

    db.exec(migration3);

    assert.deepEqual(
      db.prepare(`SELECT email, include_latest FROM release_access_policies ORDER BY email`)
        .all()
        .map(({ email, include_latest }) => ({ email, include_latest })),
      [
        { email: 'latest@example.com', include_latest: 1 },
        { email: 'pinned@example.com', include_latest: 0 },
      ],
    );
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_account_versions').get().count, 1);
  } finally {
    db.close();
  }
});

test('release access policies enforce constraints and cascade with accounts', () => {
  const db = database();
  try {
    insertInterest(db);
    insertAccount(db);
    db.prepare(`
      INSERT INTO release_access_policies (email, include_latest)
      VALUES ('person@example.com', 1)
    `).run();
    assert.throws(
      () => db.exec(`UPDATE release_access_policies SET include_latest = 2`),
      /CHECK constraint failed/,
    );
    assert.throws(
      () => db.exec(`INSERT INTO release_access_policies (email) VALUES ('missing@example.com')`),
      /FOREIGN KEY constraint failed/,
    );
    db.exec(`DELETE FROM release_accounts WHERE email = 'person@example.com'`);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_access_policies').get().count, 0);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
  } finally {
    db.close();
  }
});

test('migration creates the required lookup indexes and leaves SQLite healthy', () => {
  const db = database();
  try {
    const indexes = db.prepare(`
      SELECT name, tbl_name FROM sqlite_master
      WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
    `).all();
    const columns = Object.fromEntries(indexes.map(({ name }) => [
      name,
      db.prepare(`PRAGMA index_info(${name})`).all().map(({ name: column }) => column),
    ]));
    assert.ok(Object.values(columns).some((value) => value.join(',') === 'email,expires_at'));
    assert.ok(Object.values(columns).some((value) => value.join(',') === 'email,created_at'));
    assert.ok(Object.values(columns).some((value) => value.join(',') === 'version'));
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
    assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
  } finally {
    db.close();
  }
});

test('update grants bind one opaque token to an account, version, asset, and expiry', () => {
  const db = database();
  try {
    insertInterest(db, 'recipient@example.com');
    insertAccount(db, 'recipient@example.com');
    db.exec(`
      INSERT INTO release_update_grants
        (token_hash, email, version, asset_id, expires_at)
      VALUES ('hash', 'recipient@example.com', 'v1.2.3', 'windows-x64',
              '2026-07-26T23:15:00.000Z')
    `);
    assert.deepEqual(
      { ...db.prepare(`
        SELECT token_hash, email, version, asset_id, expires_at
        FROM release_update_grants
      `).get() },
      {
        token_hash: 'hash',
        email: 'recipient@example.com',
        version: 'v1.2.3',
        asset_id: 'windows-x64',
        expires_at: '2026-07-26T23:15:00.000Z',
      },
    );
    assert.throws(
      () => db.exec(`
        INSERT INTO release_update_grants
          (token_hash, email, version, asset_id, expires_at)
        VALUES ('orphan', 'missing@example.com', 'v1.2.3', 'windows-x64', 'later')
      `),
      /FOREIGN KEY constraint failed/,
    );
    for (const [token, version, asset] of [
      ['bad-version', '1.2.3', 'windows-x64'],
      ['bad-asset', 'v1.2.3', 'Windows-x64'],
      ['bad-id', 'v1.2.3', 'unknown'],
    ]) {
      assert.throws(
        () => db.prepare(`
          INSERT INTO release_update_grants
            (token_hash, email, version, asset_id, expires_at)
          VALUES (?, 'recipient@example.com', ?, ?, 'later')
        `).run(token, version, asset),
        /CHECK constraint failed/,
      );
    }
    assert.throws(
      () => db.exec(`
        INSERT INTO release_update_grants
          (token_hash, email, version, asset_id, expires_at)
        VALUES ('hash', 'recipient@example.com', 'v1.2.4', 'linux-x64', 'later')
      `),
      /UNIQUE constraint failed/,
    );
    const expiryIndex = db.prepare(`
      SELECT name FROM sqlite_master
      WHERE type = 'index' AND tbl_name = 'release_update_grants'
    `).all().find(({ name }) => (
      db.prepare(`PRAGMA index_info(${name})`).all().map(({ name: column }) => column)
        .join(',') === 'expires_at'
    ));
    assert.ok(expiryIndex);
    db.exec(`DELETE FROM release_accounts WHERE email = 'recipient@example.com'`);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_update_grants').get().count, 0);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
  } finally {
    db.close();
  }
});
