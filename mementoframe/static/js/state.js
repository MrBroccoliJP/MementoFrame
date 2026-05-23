/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 */

/**
 * @file state.js
 * @description Shared application state — single source of truth for all modules.
 *
 * Exported as a single mutable object so every module reads and writes
 * the same reference. No state is duplicated across modules.
 */

export const state = {
  /**
   * Network connection status.
   * @type {boolean}
   */
  online: false,

  /**
   * Application configuration loaded from backend.
   * @type {Object}
   */
  config: {},

  /**
   * Clock and calendar tracking.
   */
  clocks: {
    clock1Tz: "UTC",
    clock2Tz: "UTC",
    clock1Label: "",
    clock2Label: "",
    enableSecond: false,
    lastCalendarDate: null,
  },

  /**
   * Display panel layouts, dimensions, and explicit widget views.
   */
  panels: {
    /** Whether the right panel is currently positioned on the left side. */
    swapped: false,

    /** Whether the calendar is currently in its 10-minute full-opacity mode. */
    bigModeActive: false,

    /** Whether Spotify is currently reporting active playback. */
    spotifyPlaying: false,

    // --- DYNAMIC WIDGET STATES ---
    /** * Current Spotify View mode.
     * @type {'hidden' | 'shrunk' | 'big'} 
     */
    spotifyView: 'hidden',

    /** * Current Calendar View mode.
     * @type {'hidden' | 'month' | 'week'} 
     */
    calendarView: 'month',

    /** * Current Forecast View mode.
     * @type {'hidden' | '5h-icons' | '5h-big' | '5d-big'} 
     */
    forecastView: 'hidden',
  },

  /**
   * Photo slideshow internal state tracking.
   */
  photos: {
    cyclePool: [],
    currentBatch: [],
    nextBatch: [],
    index: 0,
    thumbsContainer: null,
    thumbsReady: null,
  },

  /**
   * Weather data availability tracking.
   */
  weather: {
    /** Whether the compact current weather card has valid fresh data. */
    available: false,

    /** Whether the forecast rotation has enough valid data to render. */
    forecastAvailable: false,
  },

  /**
   * Spotify playback and background accent color tracking.
   */
  spotify: {
    pollTimer: null,
    accentTimer: null,
    currentAccent: null,
    lastTrackId: null,
    wasPaused: false,
    hideTimeout: null,
  },

  /**
   * Global timers for layout scheduling.
   */
  timers: {
    bigModeTimeout: null,       
    bigModeWindowUntil: null,   
    bigModeNextTrigger: null,  
  },
};