import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bcdesktop.pg import EmbeddedPostgres


class EmbeddedPostgresTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        self.pg = EmbeddedPostgres(Path("/fake/pgsql"), self.data_dir)

    def test_password_is_generated_once_and_stable(self):
        first = self.pg.password()
        self.assertEqual(first, self.pg.password())
        self.assertGreaterEqual(len(first), 32)

    def test_password_file_permissions_restricted(self):
        with mock.patch("bcdesktop.pg.os.chmod") as chmod:
            self.pg.password()
        chmod.assert_called_once_with(self.pg.pwfile, 0o600)

    def test_initdb_runs_with_password_auth(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.ensure_initdb()
        cmd = run.call_args.args[0]
        self.assertIn("initdb", str(cmd[0]))
        self.assertIn("-A", cmd)
        self.assertIn("scram-sha-256", cmd)
        self.assertIn("backchannel", cmd)
        self.assertIn("--no-locale", cmd)

    def test_initdb_skipped_when_cluster_exists(self):
        (self.data_dir / "pgdata").mkdir(parents=True)
        (self.data_dir / "pgdata" / "PG_VERSION").write_text("16")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            self.pg.ensure_initdb()
        run.assert_not_called()

    def test_start_binds_localhost_only_on_given_port(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.start(54321)
        cmd = run.call_args.args[0]
        self.assertIn("pg_ctl", str(cmd[0]))
        opts = cmd[cmd.index("-o") + 1]
        self.assertIn("-p 54321", opts)
        self.assertIn("listen_addresses=127.0.0.1", opts)

    def test_stop_is_noop_without_pidfile(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            self.pg.stop()
        run.assert_not_called()

    def test_recover_stale_removes_pidfile_when_not_running(self):
        pgdata = self.data_dir / "pgdata"
        pgdata.mkdir(parents=True)
        pidfile = pgdata / "postmaster.pid"
        pidfile.write_text("99999")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=3)  # pg_ctl status: not running
            self.pg.recover_stale()
        self.assertFalse(pidfile.exists())

    def test_recover_stale_keeps_pidfile_when_running(self):
        pgdata = self.data_dir / "pgdata"
        pgdata.mkdir(parents=True)
        pidfile = pgdata / "postmaster.pid"
        pidfile.write_text("1234")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)  # pg_ctl status: running
            self.pg.recover_stale()
        self.assertTrue(pidfile.exists())

    def test_database_url_shape(self):
        url = self.pg.database_url(54321)
        self.assertTrue(url.startswith("postgresql+asyncpg://backchannel:"))
        self.assertIn("@127.0.0.1:54321/postgres", url)


if __name__ == "__main__":
    unittest.main()
