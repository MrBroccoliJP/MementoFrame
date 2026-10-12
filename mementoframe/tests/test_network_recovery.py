from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import network_manager_service as network


class NetworkRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config_file = self.root / "config.json"
        self.flag = self.root / "rebooted_for_ap_failure.flag"
        self.activity = self.root / "activity.json"
        patches = mock.patch.multiple(
            network,
            CONFIG_FILE=str(self.config_file),
            RUNTIME_DIR=str(self.root),
            AP_FAILURE_REBOOT_FLAG_FILE=str(self.flag),
            CONFIG_PORTAL_ACTIVITY_FILE=str(self.activity),
            _ap_failed_since=None,
            _ap_start_time=0.0,
            _last_probe=0.0,
            _reconnect_in_progress=False,
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.run = self.patch("run", return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.patch("sh", return_value="")
        self.patch("print", create=True)
        self.monotonic = self.patch("time.monotonic", return_value=1000.0)
        self.sleep = self.patch("time.sleep")
        self.wifi = self.patch("wifi_connected", return_value=False)
        self.ready = self.patch("ap_ready", return_value=False)
        self.patch("ZoneInfo", return_value=timezone.utc)
        self.clock = self.patch("datetime")
        self.clock.now.return_value = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        self.write_config({"enabled": False})

    def patch(self, name, **kwargs):
        patcher = mock.patch("network_manager_service." + name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def write_config(self, schedule, clock="Europe/Lisbon"):
        self.config_file.write_text(json.dumps({
            "auto_power": schedule, "clock1": {"timezone": clock},
        }), encoding="utf-8")

    def age_failure(self, seconds=3601):
        network._ap_failed_since = 1000.0
        self.monotonic.return_value = 1000.0 + seconds

    def reboot_calls(self):
        return [call for call in self.run.call_args_list if call.args[0] == ["sudo", "reboot"]]

    def test_disabled_auto_power_allows_recovery_at_any_time(self):
        for hour in (0, 3, 12, 23):
            with self.subTest(hour=hour):
                self.clock.now.return_value = datetime(2026, 10, 12, hour, tzinfo=timezone.utc)
                self.assertTrue(network.recovery_reboot_allowed())
        self.write_config(None)
        self.assertTrue(network.recovery_reboot_allowed())

    def test_enabled_schedule_boundaries_and_overnight_on_period(self):
        cases = [
            ("07:00", "23:00", 6, 59, False),
            ("07:00", "23:00", 7, 0, True),
            ("07:00", "23:00", 22, 59, True),
            ("07:00", "23:00", 23, 0, False),
            ("22:00", "06:00", 21, 59, False),
            ("22:00", "06:00", 22, 0, True),
            ("22:00", "06:00", 0, 0, True),
            ("22:00", "06:00", 5, 59, True),
            ("22:00", "06:00", 6, 0, False),
            ("07:00", "07:00", 12, 0, False),
        ]
        for on, off, hour, minute, expected in cases:
            with self.subTest(on=on, off=off, hour=hour, minute=minute):
                self.write_config({"enabled": True, "on_time": on, "off_time": off})
                self.clock.now.return_value = datetime(2026, 10, 12, hour, minute, tzinfo=timezone.utc)
                self.assertEqual(network.recovery_reboot_allowed(), expected)

    def test_clock_one_timezone_is_used_instead_of_host_time(self):
        self.write_config({"enabled": True, "on_time": "07:00", "off_time": "23:00"}, "Asia/Shanghai")
        instant = datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc)
        self.clock.now.side_effect = lambda zone: instant.astimezone(zone)
        with mock.patch.object(network, "ZoneInfo", return_value=timezone(timedelta(hours=8))) as zone:
            self.assertTrue(network.recovery_reboot_allowed())
            zone.assert_called_once_with("Asia/Shanghai")

    def test_unreadable_config_and_invalid_enabled_schedule_never_authorize_reboot(self):
        for schedule in (
            {"enabled": True},
            {"enabled": True, "on_time": "24:00", "off_time": "23:00"},
            {"enabled": True, "on_time": "07:00", "off_time": "23:60"},
            {"enabled": True, "on_time": "07:0", "off_time": "23:00"},
            {"enabled": "false"},
            [],
        ):
            with self.subTest(schedule=schedule):
                self.write_config(schedule)
                self.assertFalse(network.recovery_reboot_allowed())
        self.config_file.write_text("invalid", encoding="utf-8")
        self.assertFalse(network.recovery_reboot_allowed())
        self.config_file.unlink()
        self.assertFalse(network.recovery_reboot_allowed())
        self.write_config({"enabled": True, "on_time": "07:00", "off_time": "23:00"})
        with mock.patch.object(network, "ZoneInfo", side_effect=network.ZoneInfoNotFoundError):
            self.assertFalse(network.recovery_reboot_allowed())

    def test_network_outage_without_ap_activation_failure_never_reboots(self):
        self.monotonic.return_value = 100000.0
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertFalse(self.reboot_calls())

    def test_reboot_requires_more_than_one_hour_of_continuous_ap_failure(self):
        for age in (0, 3599, 3600):
            self.age_failure(age)
            self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertFalse(self.reboot_calls())
        self.age_failure(3601)
        self.assertTrue(network.maybe_reboot_for_ap_failure())
        self.assertTrue(self.flag.exists())
        self.assertEqual(len(self.reboot_calls()), 1)

    def test_reboot_guard_survives_a_fresh_process_with_continued_ap_failure(self):
        self.age_failure()
        self.assertTrue(network.maybe_reboot_for_ap_failure())
        # A reboot/new process resets in-memory state but preserves the flag.
        network._ap_failed_since = None
        self.monotonic.return_value = 10.0
        network.record_ap_failure()
        self.monotonic.return_value = 100000.0
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertTrue(self.flag.exists())
        self.assertEqual(len(self.reboot_calls()), 1)
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertEqual(len(self.reboot_calls()), 1)

    def test_enabled_schedule_defers_failed_ap_recovery_until_on_time(self):
        self.age_failure()
        self.write_config({"enabled": True, "on_time": "07:00", "off_time": "23:00"})
        self.clock.now.return_value = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertEqual(network._ap_failed_since, 1000.0)
        self.assertFalse(self.flag.exists())
        self.clock.now.return_value = datetime(2026, 10, 12, 7, tzinfo=timezone.utc)
        self.assertTrue(network.maybe_reboot_for_ap_failure())

    def test_disabling_auto_power_releases_deferred_recovery_immediately(self):
        self.age_failure()
        self.write_config({"enabled": True, "on_time": "07:00", "off_time": "23:00"})
        self.clock.now.return_value = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.write_config({"enabled": False})
        self.assertTrue(network.maybe_reboot_for_ap_failure())

    def test_healthy_ap_or_client_connection_clears_timer_and_reboot_guard(self):
        for healthy in (self.ready, self.wifi):
            with self.subTest(healthy=healthy):
                self.age_failure()
                self.flag.write_text("already rebooted", encoding="utf-8")
                healthy.return_value = True
                self.assertFalse(network.maybe_reboot_for_ap_failure())
                self.assertIsNone(network._ap_failed_since)
                self.assertFalse(self.flag.exists())
                healthy.return_value = False
        self.assertFalse(self.reboot_calls())

    def test_probes_and_explicit_wifi_configuration_do_not_reboot(self):
        self.age_failure()
        network._reconnect_in_progress = True
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        network._reconnect_in_progress = False
        self.activity.write_text(json.dumps({"reason": "wifi-connect", "quiet_until": 99999}), encoding="utf-8")
        with mock.patch.object(network.time, "time", return_value=100):
            self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertFalse(self.reboot_calls())

    def test_dashboard_activity_does_not_block_starting_a_missing_ap(self):
        self.activity.write_text(json.dumps({"reason": "dashboard", "quiet_until": 99999}), encoding="utf-8")
        with mock.patch.object(network.time, "time", return_value=100):
            self.assertTrue(network.config_portal_active())
            self.assertFalse(network.wifi_config_transition_active())

    def test_guard_must_be_persisted_before_reboot(self):
        self.age_failure()
        with mock.patch.object(network, "create_ap_reboot_flag", return_value=False):
            self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertFalse(self.reboot_calls())

    def test_failed_reboot_command_does_not_leave_an_incorrect_one_shot_guard(self):
        self.age_failure()
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "denied")
        self.assertFalse(network.maybe_reboot_for_ap_failure())
        self.assertFalse(self.flag.exists())

    def test_ap_activation_failure_starts_timer_and_repeated_failures_preserve_it(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "failed")
        with mock.patch.object(network, "prepare_wifi_device_for_ap"):
            self.assertFalse(network.start_ap())
            self.assertEqual(network._ap_failed_since, 1000.0)
            self.monotonic.return_value = 2000.0
            self.assertFalse(network.start_ap())
            self.assertEqual(network._ap_failed_since, 1000.0)

    def test_successful_ap_start_clears_failure_and_checks_gateway(self):
        network._ap_failed_since = 10.0
        self.flag.write_text("already rebooted", encoding="utf-8")
        self.ready.side_effect = [False, True]
        with mock.patch.object(network, "prepare_wifi_device_for_ap"):
            self.assertTrue(network.start_ap())
        self.assertIsNone(network._ap_failed_since)
        self.assertFalse(self.flag.exists())
        self.assertEqual(network._ap_start_time, 1000.0)

    def test_success_exit_without_ap_gateway_is_still_an_activation_failure(self):
        with mock.patch.object(network, "prepare_wifi_device_for_ap"):
            self.assertFalse(network.start_ap())
        self.assertEqual(network._ap_failed_since, 1000.0)

    def test_ap_ready_requires_active_profile_and_gateway_address(self):
        with mock.patch.object(network, "ap_ready", wraps=self.original_ap_ready):
            with mock.patch.object(network, "ap_active", return_value=True), mock.patch.object(network, "sh", return_value="192.168.4.1/24"):
                self.assertTrue(network.ap_ready())
            with mock.patch.object(network, "ap_active", return_value=True), mock.patch.object(network, "sh", return_value="192.168.1.182/24"):
                self.assertFalse(network.ap_ready())
            with mock.patch.object(network, "ap_active", return_value=False):
                self.assertFalse(network.ap_ready())

    original_ap_ready = staticmethod(network.ap_ready)

    def test_failed_probe_restores_ap_without_an_extra_wait_per_profile(self):
        restore = self.patch("start_ap", return_value=True)
        self.patch("known_client_profiles", return_value=["Broccoli", "usa_os_dados"])
        self.patch("reset_networkmanager_for_client_mode")
        self.patch("ap_active", return_value=False)
        self.assertFalse(network.probe_reconnect())
        restore.assert_called_once()
        self.sleep.assert_not_called()
        activation = [call for call in self.run.call_args_list if "up" in call.args[0]]
        self.assertEqual(len(activation), 2)
        for call in activation:
            self.assertIn("--wait", call.args[0])
            self.assertEqual(call.kwargs["timeout"], network.PROBE_TIMEOUT + 5)
        self.assertFalse(network._reconnect_in_progress)
        self.assertIsNone(network._ap_failed_since)

    def test_probe_exception_restores_ap_and_releases_transition_guard(self):
        restore = self.patch("start_ap", return_value=True)
        self.patch("known_client_profiles", return_value=["Broccoli"])
        self.patch("reset_networkmanager_for_client_mode", side_effect=RuntimeError("test failure"))
        self.patch("ap_active", return_value=False)
        self.assertFalse(network.probe_reconnect())
        restore.assert_called_once()
        self.assertFalse(network._reconnect_in_progress)

    def test_restored_ap_gets_full_probe_interval_after_a_long_attempt(self):
        for name in ("ensure_runtime_dir", "check_for_conflicts", "ensure_ap_profile", "ensure_client_profiles_patched"):
            self.patch(name)
        self.ready.return_value = True
        self.patch("ap_should_hold", return_value=None)
        now = [1000.0]
        self.monotonic.side_effect = lambda: now[0]
        starts = []

        def probe(force=False):
            starts.append(now[0])
            now[0] += 166.0
            network._ap_start_time = now[0]

        self.patch("probe_reconnect", side_effect=probe)
        sleeps = [0]

        def sleep(seconds):
            now[0] += seconds
            sleeps[0] += 1
            if sleeps[0] == 2:
                raise StopIteration

        self.sleep.side_effect = sleep
        with self.assertRaises(StopIteration):
            network.main()
        self.assertEqual(starts, [1000.0])
        self.assertEqual(network._last_probe, 1166.0)

    def test_startup_profile_failure_keeps_retrying_without_resetting_failure_timer(self):
        self.patch("ensure_runtime_dir")
        self.patch("check_for_conflicts", return_value=True)
        profile = self.patch("ensure_ap_profile", return_value=False)
        patch_clients = self.patch("ensure_client_profiles_patched")
        times = [1000.0]
        self.monotonic.side_effect = lambda: times[0]
        sleeps = [0]

        def sleep(seconds):
            times[0] += 3602.0
            sleeps[0] += 1
            if sleeps[0] == 2:
                raise StopIteration

        self.sleep.side_effect = sleep
        with self.assertRaises(StopIteration):
            network.main()
        self.assertEqual(profile.call_count, 2)
        patch_clients.assert_not_called()
        self.assertEqual(network._ap_failed_since, 1000.0)
        self.assertEqual(len(self.reboot_calls()), 1)

    def test_shell_timeout_becomes_a_reported_failure_instead_of_hanging(self):
        # Run the original helper while mocking subprocess itself: no real commands.
        with mock.patch.object(network, "run", wraps=self.original_run), mock.patch.object(
            network.subprocess, "run", side_effect=subprocess.TimeoutExpired(["nmcli"], 30),
        ):
            result = network.run(["nmcli"], timeout=30)
            self.assertEqual(result.returncode, 124)

    original_run = staticmethod(network.run)


if __name__ == "__main__":
    unittest.main()
