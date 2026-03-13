/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file constants.js
 * @description Application-wide constants — paths, intervals, and DOM selectors.
 *
 * Centralising these values means changing a poll rate, an API path, or a
 * CSS selector only requires editing one file rather than hunting through
 * every module. All three objects are frozen at the module level; attempts
 * to modify them at runtime will throw in strict mode.
 *
 * Import only the objects you need:
 *   import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
 */

/**
 * API endpoint paths and static asset paths.
 *
 * All backend endpoints are served by api_service.py (port 5001).
 * Photo and asset paths are relative to the document root.
 *
 * @namespace PATHS
 * @property {string} CONFIG              - Config JSON endpoint.
 * @property {string} WEATHER             - Current weather JSON endpoint.
 * @property {string} SPOTIFY             - Spotify playback JSON endpoint.
 * @property {string} STATUS              - System network status JSON endpoint.
 * @property {string} SCREEN_ON           - POST to turn the screen on via GPIO.
 * @property {string} SCREEN_OFF          - POST to turn the screen off via GPIO.
 * @property {string} CONFIG_STREAM       - SSE endpoint for live config/photo change events.
 * @property {string} PHOTOS_FULL         - Base URL for full-size WebP photos (trailing slash).
 * @property {string} PHOTOS_THUMBS       - Base URL for thumbnail WebP photos (trailing slash).
 * @property {string} WEATHER_OFFLINE_ICON - Fallback icon shown when weather is unavailable.
 */
export const PATHS = {
  CONFIG:              "/config.json",
  WEATHER:             "/weather.json",
  SPOTIFY:             "/spotify.json",
  STATUS:              "/status.json",
  SCREEN_ON:           "/screen/on",
  SCREEN_OFF:          "/screen/off",
  CONFIG_STREAM:       "/config/stream",

  PHOTOS_FULL:         "/userdata/Photos/full/",
  PHOTOS_THUMBS:       "/userdata/Photos/thumbs/",

  WEATHER_OFFLINE_ICON: "/assets/Icons/weather_offline.svg",
};

/**
 * Polling and animation intervals in milliseconds.
 *
 * Adjust these to trade off responsiveness against CPU/network usage.
 * Lower values make the display more reactive; higher values reduce load.
 *
 * @namespace INTERVALS
 * @property {number} CLOCK                - Clock tick rate (1 s — updates every second).
 * @property {number} SPOTIFY              - Spotify playback poll rate (5 s).
 * @property {number} WIFI                 - Wi-Fi/connectivity check rate (30 s).
 * @property {number} WEATHER              - Weather data poll rate (30 min).
 * @property {number} PHOTOS               - Time each photo is displayed (20 s).
 * @property {number} QR                   - QR code IP refresh rate (30 s).
 * @property {number} HOURLY_CHECK         - Rate at which hourly events are checked (1 min).
 *                                          Used for the top-of-hour calendar highlight and
 *                                          the auto power schedule evaluation.
 * @property {number} SWAP_PANELS          - How often the panels swap sides (1 h).
 * @property {number} CALENDAR_FULL_TIMEOUT - How long the calendar stays at full opacity
 *                                           during the hourly highlight before dimming (5 min).
 */
export const INTERVALS = {
  CLOCK:                 1000,
  SPOTIFY:               5000,
  WIFI:                  30000,
  WEATHER:               30 * 60 * 1000,  // 30 minutes
  PHOTOS:                20000,
  QR:                    30000,
  HOURLY_CHECK:          60000,            // 1 minute
  SWAP_PANELS:           60 * 60 * 1000,  // 1 hour
  CALENDAR_FULL_TIMEOUT: 5 * 60 * 1000,   // 5 minutes
};

/**
 * CSS selector strings for all DOM elements accessed by the modules.
 *
 * Keeping selectors here means a class or ID rename in the HTML template
 * only requires updating this one file. All module code uses these keys
 * rather than hardcoded selector strings.
 *
 * @namespace SELECTORS
 *
 * Clock elements:
 * @property {string} clock1     - Primary clock time display.
 * @property {string} clock2     - Secondary clock time display.
 * @property {string} day        - Day-of-month number text element.
 * @property {string} monthYear  - Month and year text element.
 * @property {string} dualBox    - Container wrapping both clock boxes.
 * @property {string} clock1Box  - Left clock box (primary clock + region label).
 * @property {string} clock2Box  - Right clock box (secondary clock + region label).
 * @property {string} dateBox    - Date strip container (day + month/year).
 * @property {string} firstRow   - First layout row (holds clock box(es) in single mode).
 * @property {string} secondRow  - Second layout row (holds date box in dual-clock mode).
 *
 * Calendar elements:
 * @property {string} calendarBox - Calendar panel wrapper (visibility-toggled by layout.js).
 * @property {string} calendarEl  - Inner calendar element where the table is injected.
 *
 * Spotify elements:
 * @property {string} spotifyBox   - Spotify panel wrapper (visibility-toggled by layout.js).
 * @property {string} albumCover   - Album art <img> element.
 * @property {string} trackName    - Track name text element.
 * @property {string} trackArtist  - Artist name text element.
 * @property {string} trackStatus  - Play/pause icon container.
 * @property {string} liked        - Liked-song heart indicator element.
 * @property {string} progressBar  - Playback progress bar fill element.
 *
 * Weather elements:
 * @property {string} weatherBox   - Weather widget container.
 * @property {string} weatherTemp  - Temperature text element (e.g. "18.4°C").
 * @property {string} weatherCond  - Condition text element (e.g. "Partly cloudy").
 * @property {string} weatherIcon  - Condition icon <img> element.
 *
 * Layout elements:
 * @property {string} leftPanel     - Left (photo) panel.
 * @property {string} rightPanel    - Right (info) panel.
 * @property {string} wifiStatus    - Wi-Fi status indicator dot.
 * @property {string} qrContainer   - QR code render target.
 * @property {string} photoContainer - Slideshow image container within the left panel.
 * @property {string} systemInfoBox  - System info box (IP, Wi-Fi, QR code row).
 */
export const SELECTORS = {
  // Clock
  clock1:      "#clock",
  clock2:      "#clock2",
  day:         "#day-number",
  monthYear:   "#month-year",
  dualBox:     ".dual_clock-box",
  clock1Box:   ".clock-box-left",
  clock2Box:   ".clock-box-right",
  dateBox:     ".date-box",
  firstRow:    ".first-row",
  secondRow:   ".second_row",

  // Calendar
  calendarBox: "#calendar-box",
  calendarEl:  "#calendar",

  // Spotify
  spotifyBox:   "#spotify-box",
  albumCover:   "#album-cover",
  trackName:    "#track-name",
  trackArtist:  "#track-artist",
  trackStatus:  "#track-status",
  liked:        "#track-liked",
  progressBar:  "#progress-bar",

  // Weather
  weatherBox:  ".weather-box",
  weatherTemp: ".weather-temperature",
  weatherCond: ".weather-condition",
  weatherIcon: "#weather-icon",

  // Layout
  leftPanel:    ".left_panel",
  rightPanel:   ".right_panel",
  wifiStatus:   "#wifi-status",
  qrContainer:  ".qrcode_icon",
  photoContainer: ".photo",
  systemInfoBox:  ".system-info-box",
};