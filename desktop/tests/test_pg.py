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

    def test_initdb_grants_windows_acl_first(self):
        with mock.patch("bcdesktop.pg.sys.platform", "win32"), \
                mock.patch.dict("os.environ", {"USERNAME": "tester"}), \
                mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.ensure_initdb()
        first_cmd = run.call_args_list[0].args[0]
        self.assertEqual(first_cmd[0], "icacls")
        last_cmd = run.call_args_list[-1].args[0]
        self.assertIn("initdb", str(last_cmd[0]))

    def test_initdb_skips_acl_grant_off_windows(self):
        with mock.patch("bcdesktop.pg.sys.platform", "linux"), \
                mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.ensure_initdb()
        self.assertNotIn(
            "icacls", [call.args[0][0] for call in run.call_args_list]
        )

    def test_initdb_skipped_when_cluster_exists(self):
        (self.data_dir / "pgdata").mkdir(parents=True)
        (self.data_dir / "pgdata" / "PG_VERSION").write_text("16")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            self.pg.ensure_initdb()
        run.assert_not_called()

    def test_initdb_wipes_wedged_pgdata_without_pg_version(self):
        pgdata = self.data_dir / "pgdata"
        pgdata.mkdir(parents=True)
        (pgdata / "stray.txt").write_text("leftover from a crashed initdb")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.ensure_initdb()
        # rmtree removed the wedged dir entirely; nothing recreated it
        # since subprocess.run (initdb) is mocked out.
        self.assertFalse(pgdata.exists())
        cmd = run.call_args.args[0]
        self.assertIn("initdb", str(cmd[0]))

    def test_start_binds_localhost_only_on_given_port(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.start(54321)
        cmd = run.call_args.args[0]
        self.assertIn("pg_ctl", str(cmd[0]))
        opts = cmd[cmd.index("-o") + 1]
        self.assertIn("-p 54321", opts)
        self.assertIn("listen_addresses=127.0.0.1", opts)

    def test_start_raises_with_pg_ctl_log_tail_on_failure(self):
        def fake_run(cmd, **kwargs):
            kwargs["stderr"].write("FATAL: could not bind IPv4 address\n")
            return mock.Mock(returncode=1)

        with mock.patch("bcdesktop.pg.subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                self.pg.start(54321)
        self.assertIn("pg_ctl", str(ctx.exception))
        self.assertIn("could not bind IPv4 address", str(ctx.exception))

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
