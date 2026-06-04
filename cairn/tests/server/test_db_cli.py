from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from cairn.cli import main
from cairn.server.migrations import runner


class DbCliTests(unittest.TestCase):
    def test_db_status_and_migrate(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "cairn.db"
        cli = CliRunner()

        missing = cli.invoke(main, ["db", "status", "--db", str(path)])
        self.assertEqual(missing.exit_code, 0, missing.output)
        self.assertIn("exists: no", missing.output)
        self.assertIn("pending: 0001_initial, 0002_current_additive_schema", missing.output)

        migrated = cli.invoke(main, ["db", "migrate", "--db", str(path)])
        self.assertEqual(migrated.exit_code, 0, migrated.output)
        self.assertIn("applied now: 0001_initial, 0002_current_additive_schema", migrated.output)
        self.assertIn("pending: none", migrated.output)

        status = cli.invoke(main, ["db", "status", "--db", str(path)])
        self.assertEqual(status.exit_code, 0, status.output)
        self.assertIn("exists: yes", status.output)
        self.assertIn("applied: 0001_initial, 0002_current_additive_schema", status.output)
        self.assertIn("pending: none", status.output)

    def test_db_status_uses_available_migration_order(self) -> None:
        versions = tuple(migration.version for migration in runner.available_migrations())

        self.assertEqual(versions, tuple(sorted(versions)))

    def test_db_reset_creates_backup_and_restore_recovers_it(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "cairn.db"
        cli = CliRunner()

        migrated = cli.invoke(main, ["db", "migrate", "--db", str(path)])
        self.assertEqual(migrated.exit_code, 0, migrated.output)
        with path.open("ab") as _:
            pass

        reset = cli.invoke(main, ["db", "reset", "--to", "v3.2", "--db", str(path), "--yes"])
        self.assertEqual(reset.exit_code, 0, reset.output)
        self.assertIn("backup:", reset.output)
        backup_line = next(line for line in reset.output.splitlines() if line.startswith("backup:"))
        backup_path = Path(backup_line.split("backup:", 1)[1].strip())
        self.assertTrue(backup_path.exists())

        restored = cli.invoke(main, ["db", "restore", "--db", str(path), "--backup", str(backup_path), "--yes"])
        self.assertEqual(restored.exit_code, 0, restored.output)
        self.assertIn("restored:", restored.output)

    def test_dispatch_startup_failure_is_click_error(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Path(tmp.name) / "dispatch.yaml"
        config.write_text(
            "\n".join(
                [
                    'server: "http://127.0.0.1:9"',
                    "runtime:",
                    "  interval: 3",
                    "  max_workers: 2",
                    "  max_running_projects: 1",
                    "  max_project_workers: 2",
                    "  healthcheck_timeout: 2",
                    '  prompt_group: "mock"',
                    "tasks:",
                    "  bootstrap: {timeout: 9, conclude_timeout: 5}",
                    "  reason: {timeout: 5, max_intents: 3}",
                    "  explore: {timeout: 9, conclude_timeout: 5}",
                    "environments:",
                    "  - id: local-ssh",
                    "    label: Local SSH",
                    "    backend: ssh",
                    "    ssh_command: ssh local.example",
                    "    workspace_root: /tmp/cairn-local",
                    "workers:",
                    "  - name: mock",
                    "    type: mock",
                    "    task_types: [bootstrap]",
                    "    max_running: 1",
                    "    priority: 0",
                ]
            ),
            encoding="utf-8",
        )
        cli = CliRunner()

        with patch(
            "cairn.dispatcher.scheduler.loop.DispatcherLoop.__init__",
            side_effect=RuntimeError("startup failed"),
        ):
            result = cli.invoke(main, ["dispatch", "--config", str(config), "--startup-healthcheck-only"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Error: startup failed", result.output)


if __name__ == "__main__":
    unittest.main()
