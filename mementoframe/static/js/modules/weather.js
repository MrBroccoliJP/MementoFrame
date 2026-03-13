/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file weather.js
 * @description Weather display module.
 *
 * Polls GET /weather.json every `INTERVALS.WEATHER` milliseconds and
 * updates the weather widget with the current temperature, condition
 * text, and condition icon.
 *
 * The weather box is hidden on init and only made visible once valid
 * data has been received. This prevents showing an empty or broken
 * widget on startup while the Pi is still connecting to the network.
 *
 * STALE DATA HANDLING
 * If the device goes offline, the weather box is kept visible for up to
 * `STALE` milliseconds (2 hours) after the last successful update. After
 * that, the box is hidden to avoid showing outdated conditions indefinitely.
 *
 * OFFLINE FALLBACK
 * When `state.online` is false the widget shows "--°C" and "Offline" with
 * an offline icon, then applies the stale-data timeout logic above.
 *
 * The icon URL may arrive with a protocol-relative prefix ("//...") which
 * is normalised to "https://..." before being assigned to the img src.
 * A cache-busting query string is appended to force the browser to reload
 * the icon even if it was previously cached with an error.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, fetchJson } from "../utils.js";

/**
 * Timestamp of the last successful weather data fetch (ms since epoch).
 * Null until the first successful response.
 * @type {number|null}
 */
let lastWeatherAt = null;

/**
 * Maximum age of weather data before the widget is hidden when offline (ms).
 * Set to 2 hours.
 * @type {number}
 */
const STALE = 2 * 60 * 60 * 1000;

/**
 * Initialise the weather module.
 *
 * Hides the weather box immediately (it will be shown once valid data
 * arrives) then performs an initial fetch and starts the polling interval.
 */
export function initWeather() {
  const box = $(SELECTORS.weatherBox);
  if (box) box.style.display = "none";

  setInterval(updateWeather, INTERVALS.WEATHER);
  updateWeather();
}

/**
 * Fetch current weather data and update the weather widget.
 *
 * If offline:
 *   - Shows "--°C" and "Offline" placeholder values.
 *   - If data is stale (no successful fetch within STALE ms), hides the box.
 *
 * If online but the fetch fails or returns an error:
 *   - Hides the box if data is stale; otherwise leaves it as-is.
 *
 * On success:
 *   - Updates temperature, condition text, and icon.
 *   - Records `lastWeatherAt` timestamp.
 *   - Makes the weather box visible (display: flex).
 *
 * @async
 * @returns {Promise<void>}
 */
export async function updateWeather() {
  const box  = $(SELECTORS.weatherBox);
  const tEl  = $(SELECTORS.weatherTemp);
  const cEl  = $(SELECTORS.weatherCond);
  const icon = $(SELECTORS.weatherIcon);

  if (!state.online) {
    // Show degraded state while offline
    if (tEl)  tEl.textContent = "--°C";
    if (cEl)  cEl.textContent = "Offline";
    if (icon) icon.src        = PATHS.WEATHER_OFFLINE_ICON;

    // Hide widget if the cached data is too old to be meaningful
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
    }
    return;
  }

  const data = await fetchJson(PATHS.WEATHER);
  if (!data || data.error) {
    // Request failed — hide if data is stale
    if (!lastWeatherAt || Date.now() - lastWeatherAt > STALE) {
      if (box) box.style.display = "none";
    }
    return;
  }

  if (tEl)  tEl.textContent = `${data.temperature}°C`;
  if (cEl)  cEl.textContent = data.condition;

  if (icon && data.icon) {
    icon.crossOrigin = "anonymous";
    // Normalise protocol-relative URLs from WeatherAPI
    const iconUrl = data.icon.startsWith("//") ? "https:" + data.icon : data.icon;
    // Cache-bust to force reload (avoids serving a previously errored icon)
    icon.src = `${iconUrl}?t=${Date.now()}`;
  }

  lastWeatherAt        = Date.now();
  if (box) box.style.display = "flex";
}