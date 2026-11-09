"""Exercise real screen policy and Flask routes with GPIO/systemd replaced."""
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def load_service():
    spec = importlib.util.spec_from_file_location("display_under_test", APP_DIR / "display_service.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"RPi": mock.MagicMock(), "RPi.GPIO": mock.MagicMock()}), \
         mock.patch("dotenv.load_dotenv"), mock.patch.dict("os.environ", {}, clear=True):
        spec.loader.exec_module(module)
    return module


display = load_service()


class DisplayPowerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.level = True
        self.write = mock.Mock(side_effect=lambda value: setattr(self, "level", value))
        self.read = mock.Mock(side_effect=lambda: self.level)
        self.restart = mock.Mock()
        self.config = {"auto_power": {"enabled": False}}
        self.power = display.DisplayPower(lambda: self.config, self.write, self.restart, lambda: self.now,
                                          read_screen=self.read)

    def healthy(self, start=0, end=120):
        for self.now in range(start, end + 1, 10):
            self.power.heartbeat()
            self.power.tick()

    def test_gpio_drift_is_corrected_after_thirty_seconds_without_repeated_writes(self):
        self.power.tick()
        self.level = False
        self.now = 29
        self.power.tick()
        self.read.assert_not_called()
        self.assertFalse(self.level)
        self.now = 30
        with self.assertLogs(display.log, level="WARNING"):
            self.power.tick()
        self.assertTrue(self.level)
        self.assertEqual(self.write.call_count, 2)
        self.now = 60
        self.power.tick()
        self.assertEqual(self.read.call_count, 2)
        self.assertEqual(self.write.call_count, 2)

    def test_gpio_readback_respects_night_schedule_and_manual_wake(self):
        self.healthy()
        with mock.patch.object(display, "scheduled_on", return_value=False):
            self.power.tick()
            self.level = True
            self.now = 150
            self.power.heartbeat()
            with self.assertLogs(display.log, level="WARNING"):
                self.power.tick()
            self.assertFalse(self.level)
            self.power.manual(True)
            self.level = False
            self.now = 180
            self.power.heartbeat()
            with self.assertLogs(display.log, level="WARNING"):
                self.power.tick()
            self.assertTrue(self.level)

    def test_gpio_readback_keeps_screen_off_during_recovery_backoff(self):
        self.now = 180
        self.power.tick()
        self.level = True
        self.now = 210
        with self.assertLogs(display.log, level="WARNING"):
            self.power.tick()
        self.assertFalse(self.level)
        self.restart.assert_called_once()

    def test_gpio_read_failure_does_not_block_kiosk_restart(self):
        self.now = 180
        self.power.tick()
        self.read.side_effect = RuntimeError("readback unavailable")
        self.now = 300
        with self.assertLogs(display.log, level="WARNING"):
            self.power.tick()
        self.assertEqual(self.restart.call_count, 2)
        self.now = 301
        self.power.tick()
        self.read.assert_called_once()

    def test_grace_then_sixty_seconds_missing_even_if_frontend_never_starts(self):
        for self.now in (0, 60, 120, 179):
            self.power.tick()
            self.assertTrue(self.power.screen)
            self.restart.assert_not_called()
        self.now = 180
        self.power.tick()
        self.assertFalse(self.power.screen)
        self.restart.assert_called_once()

    def test_early_heartbeat_does_not_shorten_startup_grace(self):
        self.power.heartbeat()
        self.now = 179
        self.power.tick()
        self.restart.assert_not_called()
        self.now = 180
        self.power.tick()
        self.restart.assert_called_once()

    def test_night_schedule_waits_for_two_minutes_of_heartbeats(self):
        with mock.patch.object(display, "scheduled_on", return_value=False):
            self.healthy(start=80, end=190)
            self.assertTrue(self.power.screen)
            self.assertFalse(self.power.boot_complete)
            self.now = 200
            self.power.heartbeat()
            self.power.tick()
            self.assertTrue(self.power.boot_complete)
            self.assertFalse(self.power.screen)

    def test_failed_boot_heartbeat_run_does_not_count_towards_two_minutes(self):
        self.healthy(end=60)
        self.now = 125
        self.power.heartbeat()
        self.assertEqual(self.power.healthy_seconds, 0)
        self.healthy(start=135, end=235)
        self.assertFalse(self.power.boot_complete)
        self.now = 245
        self.power.heartbeat()
        self.assertTrue(self.power.boot_complete)

    def test_heartbeat_timeout_switches_off_before_restart(self):
        self.healthy()
        self.restart.side_effect = lambda: self.assertFalse(self.power.screen)
        self.now = 179
        self.power.tick()
        self.restart.assert_not_called()
        self.now = 180
        self.power.tick()
        self.restart.assert_called_once()
        self.assertFalse(self.power.screen)

    def test_recovery_waits_for_fresh_heartbeat_and_respects_schedule(self):
        self.healthy()
        self.now = 180
        self.power.tick()
        self.now = 182
        self.power.tick()
        self.assertFalse(self.power.screen)
        self.power.heartbeat()
        with mock.patch.object(display, "scheduled_on", return_value=False):
            self.power.tick()
            self.assertFalse(self.power.screen)
        self.power.tick()
        self.assertTrue(self.power.screen)

    def test_manual_wake_expires_and_watchdog_has_priority(self):
        self.healthy()
        with mock.patch.object(display, "scheduled_on", return_value=False):
            self.power.tick()
            self.assertFalse(self.power.screen)
            self.power.manual(True)
            self.assertTrue(self.power.screen)
            self.healthy(start=130, end=410)
            self.assertTrue(self.power.screen)
            self.now = 420
            self.power.heartbeat()
            self.power.tick()
            self.assertFalse(self.power.screen)
        self.now = 480
        self.power.tick()
        self.power.manual(True)
        self.assertFalse(self.power.screen)

    def test_manual_off_cannot_hide_boot_but_works_after_boot(self):
        self.power.manual(False)
        self.assertTrue(self.power.screen)
        self.healthy()
        self.assertFalse(self.power.screen)

    def test_retries_back_off_and_restart_failures_are_retried(self):
        self.restart.side_effect = RuntimeError("systemd unavailable")
        self.now = 180
        with self.assertLogs(display.log, level="WARNING"):
            self.power.tick()
        self.assertFalse(self.power.recovering)
        self.now = 299
        self.power.tick()
        self.assertEqual(self.restart.call_count, 1)
        for self.now in (300, 420, 660, 1140, 2040):
            with self.assertLogs(display.log, level="WARNING"):
                self.power.tick()
        self.assertEqual(self.restart.call_count, 6)
        self.assertEqual(self.power.retry_delay, 900)

    def test_heartbeat_during_restart_cannot_reenable_screen(self):
        self.restart.side_effect = self.power.heartbeat
        self.now = 180
        self.power.tick()
        self.assertIsNone(self.power.last_heartbeat)
        self.assertFalse(self.power.screen)

    def test_night_time_heartbeats_prevent_restarts(self):
        with mock.patch.object(display, "scheduled_on", return_value=False):
            self.healthy(end=600)
        self.assertFalse(self.power.screen)
        self.restart.assert_not_called()

    def test_schedule_boundaries_overnight_and_equal_times(self):
        for on, off, hour, minute, expected in (
            ("07:00", "23:00", 6, 59, False), ("07:00", "23:00", 7, 0, True),
            ("07:00", "23:00", 23, 0, False), ("22:00", "06:00", 23, 0, True),
            ("22:00", "06:00", 5, 59, True), ("22:00", "06:00", 6, 0, False),
            ("07:00", "07:00", 12, 0, False),
        ):
            config = {"auto_power": {"enabled": True, "on_time": on, "off_time": off}}
            with self.subTest(on=on, off=off, hour=hour, minute=minute), \
                 mock.patch.object(display, "ZoneInfo", return_value=timezone.utc):
                self.assertEqual(display.scheduled_on(config, datetime(2026, 11, 9, hour, minute, tzinfo=timezone.utc)), expected)

    def test_clock_one_timezone_controls_schedule(self):
        config = {"auto_power": {"enabled": True, "on_time": "07:00", "off_time": "23:00"},
                  "clock1": {"timezone": "Asia/Shanghai"}}
        with mock.patch.object(display, "ZoneInfo", return_value=timezone(timedelta(hours=8))) as zone:
            self.assertTrue(display.scheduled_on(config, datetime(2026, 11, 9, 23, tzinfo=timezone.utc)))
        zone.assert_called_once_with("Asia/Shanghai")

    def test_routes_accept_only_local_token_and_issue_manual_requests(self):
        with mock.patch.object(display, "power", self.power):
            client = display.app.test_client()
            self.assertEqual(client.post("/kiosk/heartbeat").status_code, 403)
            headers = {"X-Kiosk-Token": display.KIOSK_HEARTBEAT_TOKEN}
            self.assertEqual(client.post("/kiosk/heartbeat", headers=headers,
                                        environ_base={"REMOTE_ADDR": "192.168.1.10"}).status_code, 403)
            self.assertIsNone(self.power.last_heartbeat)
            self.assertEqual(client.post("/kiosk/heartbeat", headers=headers).status_code, 200)
            self.assertEqual(self.power.last_heartbeat, 0)
            self.assertEqual(client.post("/screen/on").status_code, 200)
            self.assertEqual(self.power.manual_until, 300)
            self.assertEqual(client.post("/screen/off").status_code, 200)
            self.assertTrue(self.power.manual_off)

    def test_remote_page_receives_no_heartbeat_token(self):
        with mock.patch.object(display, "render_template", return_value="frame") as render:
            client = display.app.test_client()
            client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.10"})
            self.assertEqual(render.call_args.kwargs["kiosk_heartbeat_token"], "")
            client.get("/")
            self.assertEqual(render.call_args.kwargs["kiosk_heartbeat_token"], display.KIOSK_HEARTBEAT_TOKEN)

    def test_health_reports_watchdog_state_without_extending_liveness(self):
        with mock.patch.object(display, "power", self.power):
            self.power.heartbeat()
            self.now = 40
            health = display.app.test_client().get("/health").get_json()
            self.assertEqual(health["status"], "ok")
            self.assertEqual(health["kiosk"]["heartbeat_age_seconds"], 40)
            self.assertEqual(health["kiosk"]["startup_grace_remaining_seconds"], 80)
            self.assertEqual(self.power.last_heartbeat, 0)
            self.assertNotIn(display.KIOSK_HEARTBEAT_TOKEN, str(health))


if __name__ == "__main__":
    unittest.main()
