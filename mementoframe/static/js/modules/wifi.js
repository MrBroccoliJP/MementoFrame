/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file wifi.js
 * @description Wi-Fi and internet connectivity monitoring.
 *
 * Polls GET /status.json every `INTERVALS.WIFI` milliseconds to determine
 * the current network mode, then updates `state.online` and the visual
 * Wi-Fi status indicator accordingly.
 *
 * THREE STATES:
 *   wifi-green — Pi is in client mode AND can reach the internet
 *                (confirmed by a no-cors fetch to 1.1.1.1).
 *   wifi-blue  — Pi is in AP (hotspot) mode; connected devices can reach
 *                the admin dashboard but there is no internet access.
 *   wifi-red   — No network or internet connectivity detected.
 *
 * REACTIVE UPDATES:
 *   - Online → offline: no immediate action; the Spotify module handles
 *     ambient mode and the weather module handles stale-data display.
 *   - Offline → online: triggers an immediate weather and Spotify update
 *     so the display refreshes as soon as connectivity is restored rather
 *     than waiting for the next scheduled poll.
 *
 * FALLBACK:
 *   If /status.json itself fails (e.g. api_service.py is not yet ready),
 *   the module falls back to a direct internet probe (1.1.1.1) to still
 *   determine a meaningful green/red state.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";
import { updateWeather } from "./weather.js";
import { updateSpotify } from "./spotify.js";

/**
 * Initialise the Wi-Fi status monitor.
 *
 * Performs an immediate status check then schedules recurring checks
 * every `INTERVALS.WIFI` milliseconds.
 */
export function initWiFi() {
  setInterval(updateWiFiStatus, INTERVALS.WIFI);
  updateWiFiStatus();
}

/**
 * Check network mode and internet connectivity, then update the UI.
 *
 * Steps:
 *   1. Fetch /status.json to determine if the Pi is in AP or client mode.
 *   2. If AP mode: mark offline (no internet), set indicator to blue.
 *   3. If client mode: probe 1.1.1.1 with a no-cors fetch to confirm
 *      internet access. Green on success, red on failure.
 *   4. If /status.json itself fails: fall back to the 1.1.1.1 probe.
 *   5. Apply the appropriate CSS class to the status indicator element.
 *   6. If connectivity just restored (prevOnline was false, now true):
 *      immediately trigger weather and Spotify updates.
 *
 * @async
 * @returns {Promise<void>}
 */
async function updateWiFiStatus() {
  const statusDiv = $(SELECTORS.wifiStatus);
  const prevOnline = state.online;
  let apMode = false;
  let klass  = "wifi-red";

  try {
    const data = await fetchJson(PATHS.STATUS);

    if (data?.mode === "ap") {
      // AP mode — hotspot is active, no internet
      apMode       = true;
      state.online = false;
      klass        = "wifi-blue";
    } else {
      // Client mode — probe internet directly
      try {
        await fetch("https://1.1.1.1", { mode: "no-cors" });
        state.online = true;
        klass        = "wifi-green";
      } catch {
        state.online = false;
        klass        = "wifi-red";
      }
    }

  } catch {
    // /status.json unreachable — fall back to direct internet probe
    try {
      await fetch("https://1.1.1.1", { mode: "no-cors" });
      state.online = true;
      klass        = "wifi-green";
    } catch {
      state.online = false;
      klass        = "wifi-red";
    }
  }

  // Update the visual indicator
  if (statusDiv) statusDiv.className = "wifistatus " + klass;

  // React to connectivity changes
  if (state.online && !prevOnline) {
    // Just came online — refresh data-dependent modules immediately
    updateWeather();
    updateSpotify();
  }
  // Note: offline → online transition for Spotify ambient mode is handled
  // inside spotify.js itself when updateSpotify detects no data.
}