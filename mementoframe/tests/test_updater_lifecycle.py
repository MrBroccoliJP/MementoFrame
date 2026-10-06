from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import updater  # noqa: E402


class UpdaterLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "mementoframe"
        self.runtime = self.root / "runtime"
        self.backups = Path(self.temp_dir.name) / "backups"
        self.runtime.mkdir(parents=True)
        (self.root / "version_info.py").write_text(
            'GLOBAL_APP_VERSION = "1.0.0"\n',
            encoding="utf-8",
        )
        (self.root / "config.json").write_text(
            json.dumps({"updates": {"preserve": updater.DEFAULT_PRESERVE}}),
            encoding="utf-8",
        )

        self.paths = mock.patch.multiple(
            updater,
            PROJECT_ROOT=self.root,
            CONFIG_FILE=self.root / "config.json",
            RUNTIME_DIR=self.runtime,
            STATE_FILE=self.runtime / "update_state.json",
            STATE_LOCK_FILE=self.runtime / "update_state.lock",
            UPDATER_LOCK_FILE=self.runtime / "updater.lock",
            DOWNLOAD_DIR=self.runtime / "update_downloads",
            BACKUP_ROOT=self.backups,
            REPAIR_HELPER=self.root / "repair_services.sh",
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def read_state(self) -> dict:
        return json.loads(updater.STATE_FILE.read_text(encoding="utf-8"))

    def test_release_copy_and_backup_leave_runtime_state_untouched(self) -> None:
        active_state = '{"update_in_progress": true, "update_phase": "applying"}'
        updater.STATE_FILE.write_text(active_state, encoding="utf-8")
        (self.runtime / "update_downloads").mkdir()
        (self.runtime / "update_downloads" / "release.zip").write_bytes(b"staged archive")
        (self.root / ".env").write_text("SECRET=kept\n", encoding="utf-8")
        userdata = self.root / "resources" / "userdata"
        userdata.mkdir(parents=True)
        (userdata / "photo.txt").write_text("kept", encoding="utf-8")

        release = Path(self.temp_dir.name) / "release"
        (release / "runtime").mkdir(parents=True)
        (release / "runtime" / "update_state.json").write_text("{}", encoding="utf-8")
        (release / "app.py").write_text("# new release\n", encoding="utf-8")

        updater.copy_tree_contents(release, self.root, updater.DEFAULT_PRESERVE)

        self.assertEqual(updater.STATE_FILE.read_text(encoding="utf-8"), active_state)
        self.assertTrue((self.root / "app.py").exists())

        backup = updater.backup_current(updater.DEFAULT_PRESERVE)
        self.assertTrue((backup / "app.py").exists())
        self.assertFalse((backup / "runtime").exists())
        self.assertFalse((backup / "config.json").exists())
        self.assertFalse((backup / ".env").exists())
        self.assertFalse((backup / "resources" / "userdata").exists())
        self.assertEqual(updater.STATE_FILE.read_text(encoding="utf-8"), active_state)

    def test_successful_apply_never_deletes_the_live_runtime_directory(self) -> None:
        archive_dir = self.runtime / "update_downloads"
        archive_dir.mkdir()
        archive = archive_dir / "v2.0.0.zip"
        with zipfile.ZipFile(archive, "w") as release_zip:
            release_zip.writestr("repo/mementoframe/config_portal_service.py", "# release config service\n")
            release_zip.writestr("repo/mementoframe/display_service.py", "# release display service\n")
            release_zip.writestr("repo/mementoframe/new_release_file.py", "RELEASE = 2\n")

        updater.write_state(
            available=True,
            latest_version="2.0.0",
            latest_tag="v2.0.0",
            zipball_url="https://example.invalid/release.zip",
            downloaded_archive=str(archive),
            downloaded_zipball_url="https://example.invalid/release.zip",
            download_ready=True,
        )
        original_rmtree = updater.shutil.rmtree

        def guarded_rmtree(path, *args, **kwargs):
            self.assertNotEqual(
                Path(path).resolve(),
                self.runtime.resolve(),
                "the active runtime directory must never be replaced during apply",
            )
            return original_rmtree(path, *args, **kwargs)

        def cleanup_after_overlay_latch(*_args, **_kwargs):
            state = self.read_state()
            self.assertFalse(state["download_in_progress"])
            self.assertTrue(state["update_in_progress"])
            self.assertEqual(state["update_phase"], "applying")
            return []

        with mock.patch.object(updater.shutil, "rmtree", side_effect=guarded_rmtree), mock.patch.object(
            updater, "cleanup_special_files", side_effect=cleanup_after_overlay_latch
        ), mock.patch.object(
            updater, "repair_runtime_permissions", return_value=[]
        ), mock.patch.object(updater, "install_requirements"), mock.patch.object(
            updater, "repair_systemd_services_if_needed", return_value={"ok": True}
        ), mock.patch.object(updater, "system_boot_id", return_value="boot-a"):
            result = updater.apply_update()

        self.assertTrue(result["update_in_progress"])
        self.assertFalse(result["download_in_progress"])
        self.assertTrue(result["pending_restart"])
        self.assertEqual(result["update_phase"], "awaiting_reboot")
        self.assertTrue(updater.STATE_FILE.exists())
        self.assertTrue((self.root / "new_release_file.py").exists())

    def test_apply_keeps_overlay_hidden_while_checking_for_an_update(self) -> None:
        observed = {}

        def fake_check_for_update(
            *,
            stage_download: bool = True,
        ) -> dict:
            observed.update(self.read_state())
            self.assertFalse(stage_download)
            return updater.write_state(available=False, zipball_url=None)

        with mock.patch.object(updater, "check_for_update", side_effect=fake_check_for_update):
            result = updater.apply_update()

        self.assertTrue(observed["download_in_progress"])
        self.assertFalse(observed["update_in_progress"])
        self.assertEqual(observed["update_phase"], "downloading")
        self.assertFalse(result["download_in_progress"])
        self.assertFalse(result["update_in_progress"])
        self.assertEqual(result["update_phase"], "idle")

    def test_apply_keeps_overlay_hidden_during_archive_download(self) -> None:
        observed = {}
        updater.write_state(
            available=True,
            latest_version="2.0.0",
            latest_tag="v2.0.0",
            zipball_url="https://example.invalid/release.zip",
        )

        def fake_stage_release_download(_state: dict) -> dict:
            observed.update(self.read_state())
            raise RuntimeError("simulated download failure")

        with mock.patch.object(
            updater,
            "stage_release_download",
            side_effect=fake_stage_release_download,
        ), self.assertRaisesRegex(RuntimeError, "simulated download failure"):
            updater.apply_update()

        failed = self.read_state()
        self.assertTrue(observed["download_in_progress"])
        self.assertFalse(observed["update_in_progress"])
        self.assertEqual(observed["update_phase"], "downloading")
        self.assertFalse(failed["download_in_progress"])
        self.assertFalse(failed["update_in_progress"])
        self.assertEqual(failed["update_phase"], "failed")

    def test_auto_update_does_not_latch_overlay_before_apply(self) -> None:
        observed = {}

        def fake_check_for_update(
            *,
            stage_download: bool = True,
        ) -> dict:
            self.assertFalse(stage_download)
            return updater.write_state(
                available=True,
                latest_version="2.0.0",
                latest_tag="v2.0.0",
                zipball_url="https://example.invalid/release.zip",
            )

        def fake_apply_update(*_args, **_kwargs) -> dict:
            observed.update(self.read_state())
            return updater.write_state(
                download_in_progress=False,
                update_in_progress=False,
                update_phase="idle",
                applied_update=False,
            )

        with mock.patch.object(updater, "repair_systemd_services_if_needed", return_value={"ok": True}), mock.patch.object(
            updater,
            "load_config",
            return_value={"updates": {"auto_update": True}, "auto_power": {}},
        ), mock.patch.object(updater, "in_auto_update_window", return_value=True), mock.patch.object(
            updater, "auto_update_target_minute", return_value=420
        ), mock.patch.object(updater, "cached_archive_for_state", return_value=None), mock.patch.object(
            updater, "check_for_update", side_effect=fake_check_for_update
        ), mock.patch.object(updater, "apply_update", side_effect=fake_apply_update):
            updater.autoupdate(no_reboot=True)

        self.assertFalse(observed.get("download_in_progress", False))
        self.assertFalse(observed.get("update_in_progress", False))
        self.assertNotEqual(observed.get("update_phase"), "applying")

    def test_auto_update_recovers_an_orphaned_apply_state(self) -> None:
        stale = updater.write_state(
            update_in_progress=True,
            update_phase="applying",
            update_started_at=1,
        )
        stale["state_updated_at"] = 1
        updater.atomic_write_json(updater.STATE_FILE, stale)

        with mock.patch.object(updater, "repair_systemd_services_if_needed", return_value={"ok": True}), mock.patch.object(
            updater, "load_config", return_value={"updates": {"auto_update": False}}
        ):
            result = updater.autoupdate(no_reboot=True)

        self.assertFalse(result["update_in_progress"])
        self.assertEqual(result["update_phase"], "interrupted")
        self.assertEqual(result["auto_update_skipped"], "disabled")

    def test_post_reboot_check_waits_for_a_new_boot_then_completes(self) -> None:
        updater.write_state(
            update_in_progress=True,
            update_phase="awaiting_reboot",
            pending_restart=True,
            reboot_requested=True,
            update_applied_boot_id="boot-a",
        )

        with mock.patch.object(updater, "system_boot_id", return_value="boot-a"), mock.patch.object(
            updater, "url_ok"
        ) as health_check:
            waiting = updater.post_reboot_check()

        health_check.assert_not_called()
        self.assertTrue(waiting["update_in_progress"])
        self.assertTrue(waiting["pending_restart"])
        self.assertEqual(waiting["update_phase"], "awaiting_reboot")

        with mock.patch.object(updater, "system_boot_id", return_value="boot-b"), mock.patch.object(
            updater, "url_ok", return_value=True
        ), mock.patch.object(updater, "prune_old_backups", return_value={}):
            complete = updater.post_reboot_check()

        self.assertFalse(complete["update_in_progress"])
        self.assertFalse(complete["pending_restart"])
        self.assertFalse(complete["reboot_requested"])
        self.assertEqual(complete["update_phase"], "complete")

    def test_post_reboot_check_uses_timestamp_when_boot_id_is_unavailable(self) -> None:
        updater.write_state(
            update_in_progress=True,
            update_phase="awaiting_reboot",
            pending_restart=True,
            reboot_requested=True,
            reboot_requested_at=200,
            update_applied_boot_id=None,
            reboot_requested_boot_id=None,
        )

        with mock.patch.object(updater, "system_boot_id", return_value=None), mock.patch.object(
            updater, "system_boot_time", return_value=100
        ), mock.patch.object(updater, "url_ok") as health_check:
            waiting = updater.post_reboot_check()

        health_check.assert_not_called()
        self.assertTrue(waiting["pending_restart"])
        self.assertEqual(waiting["update_phase"], "awaiting_reboot")

        with mock.patch.object(updater, "system_boot_id", return_value=None), mock.patch.object(
            updater, "system_boot_time", return_value=300
        ), mock.patch.object(updater, "url_ok", return_value=True), mock.patch.object(
            updater, "prune_old_backups", return_value={}
        ):
            complete = updater.post_reboot_check()

        self.assertFalse(complete["pending_restart"])
        self.assertEqual(complete["update_phase"], "complete")

    def test_successful_rollback_verification_clears_original_update_pending_state(self) -> None:
        updater.write_state(
            update_in_progress=True,
            update_phase="awaiting_rollback_reboot",
            pending_restart=True,
            reboot_requested=True,
            post_reboot_pending=True,
            post_reboot_waiting_for_restart=True,
            rollback_in_progress=True,
            rollback_reboot_requested=True,
            rollback_applied_boot_id="boot-a",
        )

        with mock.patch.object(updater, "system_boot_id", return_value="boot-b"), mock.patch.object(
            updater, "url_ok", return_value=True
        ):
            complete = updater.post_rollback_check()

        self.assertFalse(complete["update_in_progress"])
        self.assertFalse(complete["post_reboot_pending"])
        self.assertFalse(complete["post_reboot_waiting_for_restart"])
        self.assertFalse(complete["post_rollback_pending"])
        self.assertEqual(complete["update_phase"], "complete")

    def test_reboot_failure_keeps_overlay_lifecycle_active(self) -> None:
        updater.write_state(
            update_in_progress=True,
            update_phase="awaiting_reboot",
            pending_restart=True,
            applied_update=True,
        )
        failed = subprocess.CompletedProcess(
            args=["sudo", "reboot"],
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

        with mock.patch.object(updater, "system_boot_id", return_value="boot-a"), mock.patch.object(
            updater, "sudo_cmd", return_value=failed
        ), mock.patch("builtins.print"):
            result = updater.request_reboot()

        self.assertTrue(result["update_in_progress"])
        self.assertTrue(result["pending_restart"])
        self.assertTrue(result["reboot_requested"])
        self.assertEqual(result["update_phase"], "awaiting_reboot")
        self.assertIn("reboot failed", result["last_error"].lower())

    def test_state_revisions_increase_for_every_write(self) -> None:
        first = updater.write_state(update_in_progress=True)
        second = updater.write_state(update_phase="applying")
        third = updater.replace_state(available=True)

        self.assertLess(first["state_revision"], second["state_revision"])
        self.assertLess(second["state_revision"], third["state_revision"])
        self.assertTrue(third["update_in_progress"])
        self.assertEqual(third["update_phase"], "applying")

    def test_second_updater_cannot_enter_the_operation_lock(self) -> None:
        with updater.interprocess_file_lock(updater.UPDATER_LOCK_FILE) as first_acquired:
            self.assertTrue(first_acquired)
            with updater.interprocess_file_lock(
                updater.UPDATER_LOCK_FILE,
                blocking=False,
            ) as second_acquired:
                self.assertFalse(second_acquired)

    def test_only_an_orphaned_apply_state_can_be_retried(self) -> None:
        now = 1_000.0
        fresh_apply = {
            "update_in_progress": True,
            "update_phase": "applying",
            "state_updated_at": now - 5,
        }
        stale_apply = {**fresh_apply, "state_updated_at": now - 60}

        self.assertFalse(
            updater.can_start_background_update(
                fresh_apply,
                operation_slot_available=True,
                current_time=now,
            )
        )
        self.assertFalse(
            updater.can_start_background_update(
                stale_apply,
                operation_slot_available=False,
                current_time=now,
            )
        )
        self.assertTrue(
            updater.can_start_background_update(
                stale_apply,
                operation_slot_available=True,
                current_time=now,
            )
        )
        self.assertFalse(
            updater.can_start_background_update(
                {**stale_apply, "pending_restart": True, "update_phase": "awaiting_reboot"},
                operation_slot_available=True,
                current_time=now,
            )
        )


if __name__ == "__main__":
    unittest.main()
