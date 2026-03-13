/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file power.js
 * @description Auto power schedule and screen on/off control.
 *
 * Sends HTTP POST requests to the backend (api_service.py) to toggle the
 * physical screen via GPIO:
 *   POST /screen/on  — drives GPIO pin HIGH (screen on)
 *   POST /screen/off — drives GPIO pin LOW  (screen off)
 *
 * On startup the screen is always forced on, regardless of the schedule,
 * to ensure the display is visible after a reboot.
 *
 * If auto_power is enabled in config.json the schedule is evaluated every
 * `INTERVALS.HOURLY_CHECK` milliseconds. The schedule supports overnight
 * ranges (e.g. off at 23:00, on at 07:00) by detecting when off_time is
 * later in the day than on_time and inverting the logic accordingly.
 *
 * Schedule state is read from `state.config.auto_power` which is
 * populated by config.js. The evaluation timezone matches clock 1's
 * timezone so the schedule respects the user's local time.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS } from "../constants.js";

/**
 * Initialise the power management module.
 *
 * Forces the screen on immediately at startup (covers the case where the
 * Pi reboots during an off period and the screen would otherwise stay off).
 * Schedules `checkScreenSchedule` to run every `INTERVALS.HOURLY_CHECK`
 * milliseconds so the schedule is evaluated periodically.
 */
export function initPower() {
  fetch(PATHS.SCREEN_ON, { method: "POST" })
    .then(() => console.log("🖥️ Screen: forced ON at startup"))
    .catch(err => console.error("⚠️ Failed to wake screen:", err));

  setInterval(checkScreenSchedule, INTERVALS.HOURLY_CHECK);
}

/**
 * Evaluate the auto power schedule and toggle the screen accordingly.
 *
 * Skips evaluation if `auto_power` is not set or not enabled in config.
 *
 * Algorithm:
 *   1. Parse off_time and on_time into hours and minutes.
 *   2. Build Date objects for today at those times in clock 1's timezone.
 *   3. If off_time < on_time (same-day range, e.g. 02:00–06:00):
 *        shouldOff = now is within [off_time, on_time).
 *   4. If off_time >= on_time (overnight range, e.g. 23:00–07:00):
 *        shouldOff = now >= off_time OR now < on_time.
 *   5. POSTs to /screen/off or /screen/on accordingly.
 */
export function checkScreenSchedule() {
  const ap = state.config?.auto_power;
  if (!ap || !ap.enabled) return;

  const tz  = state.clocks.clock1Tz;
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: tz }));

  const off = parseHM(ap.off_time);
  const on  = parseHM(ap.on_time);

  const offDate = new Date(now); offDate.setHours(off.h, off.m, 0, 0);
  const onDate  = new Date(now); onDate.setHours(on.h,  on.m,  0, 0);

  let shouldOff = false;
  if (offDate < onDate) {
    // Same-day window: off during [offDate, onDate)
    shouldOff = now >= offDate && now < onDate;
  } else {
    // Overnight window: off from offDate until midnight, and from midnight until onDate
    shouldOff = now >= offDate || now < onDate;
  }

  fetch(shouldOff ? PATHS.SCREEN_OFF : PATHS.SCREEN_ON, { method: "POST" })
    .then(r => r.json())
    .then(d => console.log("🖥️ Screen:", d.status))
    .catch(err => console.error("⚠️ Screen update failed:", err));
}

/**
 * Parse a "HH:MM" time string into hours and minutes.
 *
 * Handles missing or malformed strings by defaulting to "00:00".
 *
 * @param {string} [str="00:00"] - Time string in "HH:MM" format.
 * @returns {{ h: number, m: number }} Object with `h` (hours) and `m` (minutes).
 */
function parseHM(str = "00:00") {
  const [h, m] = (str || "00:00").split(":").map(n => parseInt(n, 10) || 0);
  return { h, m };
}