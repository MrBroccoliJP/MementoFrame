/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file main.js
 * @description Application entry point — boots all display modules in order.
 *
 * Waits for the DOM to be ready via `DOMContentLoaded`, then:
 *
 *   1. Sets the calendar to ambient opacity (0.75) immediately so there
 *      is no flash of full-brightness calendar before config loads.
 *   2. Awaits `loadConfig()` so that timezone, clock labels, and power
 *      settings are available in `state` before any module starts reading them.
 *   3. Initialises all feature modules in dependency order:
 *        - Clocks       — requires state.clocks (set by loadConfig)
 *        - Photos       — independent; reads window.photos from photos.js
 *        - Spotify      — independent; starts polling immediately
 *        - Weather      — independent; starts polling immediately
 *        - WiFi         — independent; drives state.online for other modules
 *        - Power        — requires state.config.auto_power (set by loadConfig)
 *        - QR           — independent; polls /get_ip
 *   4. Starts two recurring global behaviours:
 *        - `checkHourlyCalendarDisplay` — every INTERVALS.HOURLY_CHECK ms,
 *          shows the calendar at full opacity at the top of each hour.
 *        - `swapPanels` — every INTERVALS.SWAP_PANELS ms (1 hour), toggles
 *          the left/right panel layout for visual variety.
 *   5. Opens the SSE config watcher so the display reloads when settings
 *      are saved via the admin dashboard.
 *
 * DEV HELPERS
 * Three globals are exposed on `window` for in-browser debugging:
 *   - `swapPanels()`  — manually trigger a panel swap
 *   - `burstPhotos()` — manually trigger the photo burst animation
 *   - `state`         — inspect the full application state object
 */

import { INTERVALS } from "./constants.js";
import { state } from "./state.js";
import { loadConfig, setupConfigWatcher } from "./modules/config.js";
import { initClocks } from "./modules/clock.js";
import { initPhotos, burstPhotos } from "./modules/photoslideshow.js";
import { initSpotify } from "./modules/spotify.js";
import { initWeather } from "./modules/weather.js";
import { initWiFi } from "./modules/wifi.js";
import { swapPanels, checkHourlyCalendarDisplay, setCalendarOpacity } from "./modules/layout.js";
import { initPower } from "./modules/power.js";
import { initQR } from "./modules/qr.js";
import { loadVersions, hideLoadingScreen, setLoadingStatus, delay } from "./modules/loading.js";

window.addEventListener("DOMContentLoaded", async () => {
  setCalendarOpacity(0.75);

  setLoadingStatus("Loading config");
  await loadConfig();

  setLoadingStatus("Loading versions");
  await loadVersions();

  setLoadingStatus("Starting modules");
  initClocks();
  initPhotos();
  initSpotify();
  initWeather();
  initWiFi();
  initPower();
  initQR();

  setInterval(checkHourlyCalendarDisplay, INTERVALS.HOURLY_CHECK);
  setInterval(swapPanels, INTERVALS.SWAP_PANELS);
  setupConfigWatcher();

  await delay(2000);
  hideLoadingScreen();
});

window.swapPanels = swapPanels;
window.burstPhotos = burstPhotos;
window.state = state;