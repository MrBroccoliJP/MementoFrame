/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file config.js
 * @description Configuration loading and live-reload watcher.
 *
 * Fetches config.json from the backend (served by api_service.py at
 * GET /config.json) and hydrates the relevant sections of `state` so
 * all other modules can read clock, weather, and power settings without
 * importing config directly.
 *
 * Also opens a Server-Sent Events connection to /config/stream. When
 * api_service.py detects that config.json or photos.json has changed on
 * disk, it emits a "reload" event and this module triggers a full page
 * reload after a short debounce. This ensures the display always reflects
 * the latest settings saved via the admin dashboard (app.py, port 5000)
 * without any manual refresh.
 */

import { state } from "../state.js";
import { fetchJson } from "../utils.js";
import { PATHS } from "../constants.js";

/**
 * Fetch config.json and populate `state` with the parsed values.
 *
 * Reads clock timezones and labels, and the clock2 enabled flag.
 * Falls back to safe defaults if any field is missing so the display
 * never breaks due to an incomplete or empty config file.
 *
 * Called once during app initialisation before any module that depends
 * on `state.clocks` is started.
 *
 * @async
 * @returns {Promise<void>}
 */
export async function loadConfig() {
  const cfg = await fetchJson(PATHS.CONFIG, {});
  state.config = cfg || {};

  // Clock timezone and label defaults — used by clock.js and power.js
  state.clocks.enableSecond = cfg?.clock2?.enabled ?? false;
  state.clocks.clock1Tz     = cfg?.clock1?.timezone || "UTC";
  state.clocks.clock2Tz     = cfg?.clock2?.timezone || "UTC";
  state.clocks.clock1Label  = cfg?.clock1?.label    || "Clock 1";
  state.clocks.clock2Label  = cfg?.clock2?.label    || "Clock 2";
}

/**
 * Open an SSE connection to /config/stream and reload on file changes.
 *
 * The backend emits:
 *   - "data: ready"  — once on connect (ignored here)
 *   - "data: reload" — when config.json or photos.json changes on disk
 *   - ": heartbeat"  — every second to keep the connection alive
 *
 * On a "reload" event a 500 ms debounce is applied before calling
 * `window.location.reload()`. This prevents a rapid burst of saves
 * (e.g. multiple fields in quick succession) from triggering multiple
 * reloads.
 *
 * On SSE error the connection is automatically closed by the browser.
 * This function schedules a fresh `setupConfigWatcher()` call after
 * 5 seconds so the watcher reconnects after a Pi reboot or network blip.
 */
export function setupConfigWatcher() {
  const es = new EventSource(PATHS.CONFIG_STREAM);

  es.onmessage = (e) => {
    if (e.data === "reload") {
      // Debounce: avoid reloading multiple times if several files change at once
      setTimeout(() => window.location.reload(), 500);
    }
  };

  es.onerror = () => {
    // SSE connection lost — close the broken source and retry after a pause
    es.close();
    setTimeout(setupConfigWatcher, 5000);
  };
}