# MementoFrame AP outage test — 12 October 2026

All timestamps below are Lisbon time (UTC+01:00).

## Method

SSH used Ethernet at `192.168.1.134`; its reply route was verified to use `enxb827eb0ece55`. The two saved client Wi-Fi profiles were backed up and temporarily assigned nonexistent SSIDs. Passwords were preserved. The existing watchdog and application code were left unchanged. A separate systemd timer was installed before the outage to restore the profiles automatically after 12 minutes.

The test began at 09:58:33 and was ended early after reproducing the failure. No phone/client association test, cold boot without Wi-Fi, or hour-long outage test was performed.

## Observations

| Time | Observation |
| --- | --- |
| 09:58:33 | Client Wi-Fi disconnected; Ethernet SSH remained available. |
| 09:58:33–10:00:36 | Watchdog refused to start the AP because the dashboard activity marker was still within its five-minute grace period. The marker's last dashboard activity was approximately 09:55:38. |
| 10:00:42 | Grace period expired; AP activation began. |
| 10:00:50 | Watchdog reported AP live at 192.168.4.1. NetworkManager started its DHCP server with range 192.168.4.10–192.168.4.254. |
| 10:02:44 | Idle reconnect probe began. |
| 10:02:48 | AP stopped; watchdog restarted NetworkManager. Ethernet SSH survived. |
| 10:03:17 | First saved client profile tried. Its activation failed at 10:03:43, followed by another 45-second wait. |
| 10:04:28 | Second saved client profile tried. Its activation failed at 10:04:54, followed by another 45-second wait. |
| 10:05:39 | Watchdog began restoring AP after both profiles failed. |
| 10:05:46 | AP reported live again. |
| 10:05:52 | A second probe began only six seconds after restoration. |
| 10:05:55 | AP stopped again. |
| 10:06:26 | Original Wi-Fi settings restored and client connection active; watchdog running. |
| 10:08:29 | Final verification: both Ethernet and original Wi-Fi connected; watchdog active; test timer and logger inactive. |

## Findings

1. Dashboard activity can prevent initial AP startup for five minutes even when client Wi-Fi is absent. The same activity marker is used both to protect an existing AP and to suppress initial fallback activation.
2. Reconnect attempts take longer than the 120-second probe interval. The main loop records `_last_probe` using the timestamp from before the attempt, so a restored AP is immediately eligible for another probe. This was reproduced on the physical device, with only six seconds between AP restoration and the next probe.
3. The watchdog waits an additional 45 seconds after an explicit failed activation of each saved profile, extending AP downtime.

The startup messages about disconnecting an already inactive wlan0 did not prevent AP activation in this test. Successful AP/DHCP startup does not by itself verify a phone can associate and reach the portal.

## Subsequent local observation and limits

The user reports a different starting condition: booting without available Wi-Fi, the AP initially works, disappears after its first reconnect probe, and appears never to recover; the screen remains red and the device eventually performs the one-hour recovery reboot. That full cold-boot, Ethernet-free scenario was not reproduced by this test.

The current display code polls Wi-Fi status every 30 seconds and shows blue when the status endpoint reports the AP address. It can miss a six-second AP recovery window. Red also covers lack of internet and status errors, so the color alone cannot distinguish unsuccessful AP activation from repeated brief AP recoveries.

The watchdog's one-hour reboot timer measures absence of client Wi-Fi, not absence of AP service. A reboot therefore does not establish that AP activation had failed continuously. The current code evaluates that timer in the idle AP branch, potentially after a failed reconnect probe. The timing defect explains one possible mechanism for the reported symptoms, but sustained AP activation failure or client reachability failure remains unverified.

## Restoration and evidence

Both original client SSIDs and all saved Wi-Fi security settings were compared with the backup and matched. The automatic restore timer was cancelled only after restoration was verified. No permanent networking or application code changes were made.

Full captured logs: `journal.log` beside this report. Root-only device backup and original logs: `/var/tmp/mementoframe-ap-test-20261012-095742/`.

## Next change to test

Record the next probe interval from the end of the reconnect attempt, bound each activation attempt, and distinguish a Wi-Fi configuration transition from ordinary dashboard activity when deciding whether to start fallback AP. Repeat this outage test, then separately verify client association/portal access, recovery when Wi-Fi returns, and boot with the saved network unavailable.
