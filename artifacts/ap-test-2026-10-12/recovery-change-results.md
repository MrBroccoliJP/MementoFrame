# AP recovery change and verification — 12 October 2026

## Implemented policy

- Only continuous failure to activate the fallback AP for more than 3,600 seconds makes a recovery reboot eligible. Lack of client Wi-Fi alone does not.
- Healthy AP mode requires the active MementoAP profile and the configured 192.168.4.1 gateway. AP or client Wi-Fi recovery clears the failure timer.
- With auto power disabled, recovery may reboot at any time. With auto power enabled, it waits for the configured screen-on period, interpreted in clock 1's timezone. An unreadable config or invalid enabled schedule cannot authorize a reboot.
- A persistent, flushed runtime flag permits only one reboot during a continuous failure. A new watchdog process after that reboot preserves the guard. Failed AP startup continues to be retried, but further reboots are suppressed until AP mode or client Wi-Fi restores access.
- Deliberately stopping AP mode for a reconnect probe does not start the AP failure timer.

Reconnect commands now have bounded timeouts, skip the extra 45-second wait after a failed activation, and restore AP mode even when a probe encounters an exception. The interval for the next probe is measured from the end of the previous attempt. Ordinary dashboard activity no longer blocks starting a missing AP. Startup profile/configuration failures are retried inside the watchdog rather than restarting the service and losing the failure timer.

## Validation

All 23 tests in `mementoframe/tests/test_network_recovery.py` passed on both Windows and the Raspberry Pi. Tests include schedule boundaries, overnight on periods, clock 1 timezone selection, disabled auto power, the one-hour threshold, AP/client recovery, persisted guards after a simulated process restart, probe error recovery, and the long-probe timing regression. Reboot commands are mocked throughout those tests. Python compilation and `git diff --check` passed. The Pi's real Europe/Lisbon timezone data was verified.

The network and configuration services were installed on the Pi from the tested source, preserving prior ownership/permissions and backing up the original files. Installed normalized source hashes matched the local working copy. A temporary code rollback timer was cancelled after service health verification.

## Physical outage test

All times are Lisbon time (UTC+01:00). The saved client profiles were temporarily assigned nonexistent SSIDs, preserving passwords, while SSH used Ethernet at 192.168.1.134.

| Time | Observation |
| --- | --- |
| 10:33:36 | Wi-Fi disconnected for the outage test. |
| 10:33:44 | AP live at 192.168.4.1; portal health endpoint responded. |
| 10:35:49 | First reconnect probe began. |
| 10:36:48 | First client profile failed; second profile attempted immediately. |
| 10:37:14 | Second client profile failed; AP restoration began immediately. |
| 10:37:22 | AP restored; gateway and portal health endpoint verified. |
| 10:38:48 | AP still active, portal health endpoint responding. |
| 10:39:27 | Next probe began after a stable 125-second AP interval. Before the fix, the interval was six seconds. |
| 10:39:46 | Test ended; original client Wi-Fi restored. |
| 10:41:19 | Final verification: Ethernet and original Wi-Fi connected; both services active with zero automatic restarts; portal healthy; all test/rollback timers and loggers inactive. |

Both original SSIDs and their security settings matched the pre-test backup after restoration. No physical recovery reboot was performed. This test does not establish phone association, cold-boot recovery without Ethernet, or behavior during an actual hour-long AP hardware failure.

## Evidence and rollback

- Patched test log: `patched-verification.log` beside this report.
- Original test log: `journal.log` beside the earlier `results.md` report.
- Original service source backup on the device: `/var/tmp/mementoframe-ap-code-backup-20261012-103145/`.
- Staged tests and verification log on the device: `/var/tmp/mementoframe-ap-recovery-20261012/`.
