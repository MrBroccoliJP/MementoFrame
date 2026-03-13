/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file state.js
 * @description Shared application state — single source of truth for all modules.
 *
 * Exported as a single mutable object so every module reads and writes
 * the same reference. No state is duplicated across modules; if a module
 * needs to know something about another module's domain it reads it here.
 *
 * State is grouped into logical namespaces:
 *
 *   state.online   — Whether the device has internet access.
 *                    Set by wifi.js; read by spotify.js and weather.js
 *                    to skip API calls when offline.
 *
 *   state.config   — Raw config object loaded from config.json.
 *                    Populated by config.js; read by power.js for the
 *                    auto_power schedule.
 *
 *   state.clocks   — Clock display settings and calendar tracking.
 *                    Populated by config.js from config.json fields;
 *                    read and mutated by clock.js on every tick.
 *
 *   state.panels   — Right-panel layout flags.
 *                    Mutated by layout.js and spotify.js; read by
 *                    layout.js to compute panel dimensions and by
 *                    photoslideshow.js to position burst photos.
 *
 *   state.spotify  — Spotify widget runtime state.
 *                    Mutated exclusively by spotify.js; not read by
 *                    other modules (they use state.panels.spotifyPlaying
 *                    for layout decisions).
 *
 *   state.photos   — Slideshow runtime state.
 *                    Mutated exclusively by photoslideshow.js.
 *
 *   state.timers   — Cross-module timer handles.
 *                    Currently holds the calendar full-opacity timeout
 *                    which is set by layout.js and cleared by multiple
 *                    callers, so it lives here rather than in a closure.
 */

export const state = {
  /**
   * Whether the device currently has internet access.
   * Updated by wifi.js on every connectivity check.
   * @type {boolean}
   */
  online: false,

  /**
   * Parsed contents of config.json.
   * Populated by config.js; used by power.js (auto_power schedule).
   * @type {Object}
   */
  config: {},

  /**
   * Clock display configuration and calendar change tracking.
   * @type {Object}
   * @property {boolean}     enableSecond      - Whether the second clock (clock 2) is shown.
   * @property {string}      clock1Tz          - IANA timezone for clock 1 (e.g. "Europe/Lisbon").
   * @property {string}      clock2Tz          - IANA timezone for clock 2 (e.g. "Asia/Shanghai").
   * @property {string}      clock1Label       - Display label shown below clock 1.
   * @property {string}      clock2Label       - Display label shown below clock 2.
   * @property {string|null} lastCalendarDate  - ISO date string (YYYY-MM-DD) of the last calendar
   *                                            render in clock 1's timezone. Used to detect day
   *                                            rollovers and trigger a calendar regeneration.
   */
  clocks: {
    enableSecond:     false,
    clock1Tz:         "UTC",
    clock2Tz:         "UTC",
    clock1Label:      "Clock 1",
    clock2Label:      "Clock 2",
    lastCalendarDate: null,
  },

  /**
   * Right-panel layout flags.
   * @type {Object}
   * @property {boolean} swapped            - Whether the panels have been swapped
   *                                          (right panel moved to left side of screen).
   * @property {boolean} calendarFullOpacity - Whether the calendar is currently in
   *                                          full-opacity (hourly highlight) mode.
   *                                          When true, the left panel narrows to NARROW
   *                                          width to give the calendar more visual space.
   * @property {boolean} spotifyPlaying     - Whether Spotify is currently playing.
   *                                          When true, the Spotify widget is shown and
   *                                          the left panel narrows to NARROW width.
   */
  panels: {
    swapped:            false,
    calendarFullOpacity: false,
    spotifyPlaying:     false,
  },

  /**
   * Spotify widget runtime state.
   * @type {Object}
   * @property {string|null}  lastTrackId    - Spotify track ID of the last seen track.
   *                                          Used to detect track changes for fade transitions.
   * @property {number|null}  hideTimeout   - setTimeout handle for the 30 s grace period
   *                                          after Spotify pauses. Cleared if playback resumes.
   * @property {number|null}  accentTimer   - setInterval handle for the hourly ambient pastel
   *                                          colour cycle. Null when album-art accent is active.
   * @property {string}       currentAccent - Most recently applied CSS accent colour string.
   *                                          Used as a fallback if canvas sampling fails.
   * @property {boolean}      wasPaused     - True during a pause grace period; prevents
   *                                          duplicate hideTimeout timers from being created.
   * @property {number|null}  pollTimer     - setInterval handle for the Spotify polling loop.
   */
  spotify: {
    lastTrackId:    null,
    hideTimeout:    null,
    accentTimer:    null,
    currentAccent:  "rgb(50, 50, 50)",
    wasPaused:      false,
    pollTimer:      null,
  },

  /**
   * Photo slideshow runtime state.
   * @type {Object}
   * @property {string[]}          shuffled         - Shuffled copy of window.photos filenames.
   *                                                 Reshuffled every 36 slides (burst cycle).
   * @property {number}            index            - Current position within `shuffled`.
   * @property {HTMLDivElement|null} thumbsContainer - Hidden off-screen div holding preloaded
   *                                                  <img> elements for the burst animation.
   *                                                  Null until preloadAllThumbs() runs.
   */
  photos: {
    shuffled:        [],
    index:           0,
    thumbsContainer: null,
  },

  /**
   * Cross-module timer handles.
   * @type {Object}
   * @property {number|null} calendarFullTimeout - setTimeout handle for the calendar full-opacity
   *                                              display period. Set by layout.showCalendarFull(),
   *                                              cleared by layout.hideCalendarFull() and
   *                                              layout.showSpotify(). Lives here because multiple
   *                                              functions in layout.js need to read and clear it.
   */
  timers: {
    calendarFullTimeout: null,
  },
};