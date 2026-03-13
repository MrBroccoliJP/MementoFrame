/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file spotify.js
 * @description Spotify playback display and dynamic accent colour system.
 *
 * Polls GET /spotify.json every `INTERVALS.SPOTIFY` milliseconds and
 * updates the Spotify widget with the current track name, artist, album
 * art, progress bar, liked status, and play/pause icon.
 *
 * ACCENT COLOUR SYSTEM
 * The entire display uses a single CSS variable `--accent-color` that
 * drives border colours, calendar text, clock borders, and the Spotify
 * panel gradient. The accent is sourced from two places:
 *
 *   1. AMBIENT (no music) — A random pastel colour cycles every hour via
 *      `startAccentColorCycle`. This keeps the display visually lively
 *      even when Spotify is idle.
 *
 *   2. ALBUM ART (music playing) — When a track starts, the album art
 *      image is drawn onto a canvas and sampled pixel-by-pixel to find
 *      the dominant colour. That colour is applied as the accent.
 *      Very dark (<30 brightness) and very light (>220) pixels are
 *      excluded to avoid near-black or near-white accents.
 *      If the resulting colour is too dim (brightness < 90) it is
 *      lightened by +100 on each channel.
 *
 * VISIBILITY TRANSITIONS
 *   - When playback starts: the Spotify panel fades in, calendar hides.
 *   - When playback pauses: a 30-second grace timer runs. If playback
 *     does not resume within 30 s the panel transitions back to calendar
 *     view and the ambient colour cycle restarts.
 *   - On track change: the album art and track info fade out, update,
 *     and fade back in over 600 ms.
 *
 * Inline SVGs are used for the play/pause icons to avoid external assets.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, $$, fetchJson, onceImgLoaded } from "../utils.js";
import { showCalendar, setCalendarOpacity, updatePanelState } from "./layout.js";

/** SVG markup for the play button icon. */
const playSVG  = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M3 22v-20l18 10-18 10z"/></svg>`;

/** SVG markup for the pause button icon. */
const pauseSVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M6 2h4v20h-4zm8 0h4v20h-4z"/></svg>`;

/**
 * Initialise Spotify polling and the ambient accent colour cycle.
 *
 * Starts the hourly pastel colour cycle immediately (so the display has
 * an accent colour even before the first Spotify poll) then begins
 * polling the backend for playback state.
 */
export function initSpotify() {
  startAccentColorCycle();
  startSpotifyPolling(INTERVALS.SPOTIFY);
}

/**
 * Start (or restart) the Spotify polling interval.
 *
 * Clears any existing interval before creating a new one to prevent
 * duplicate timers if called more than once.
 *
 * @param {number} ms - Polling interval in milliseconds.
 */
function startSpotifyPolling(ms) {
  if (state.spotify.pollTimer) clearInterval(state.spotify.pollTimer);
  state.spotify.pollTimer = setInterval(updateSpotify, ms);
  updateSpotify(); // immediate first call
}

/**
 * Write an accent colour to the CSS custom property and state.
 *
 * Sets both `--accent-color` and `--accent-text` on `:root` so that any
 * element using these variables updates instantly.
 *
 * @param {string} color - Any valid CSS colour string.
 */
function setAccentVar(color) {
  document.documentElement.style.setProperty("--accent-color", color);
  document.documentElement.style.setProperty("--accent-text",  color);
  state.spotify.currentAccent = color;
}

/**
 * Ensure an RGB colour is bright enough to be readable on a dark background.
 *
 * Calculates perceptual brightness using the standard luma formula
 * (0.299R + 0.587G + 0.114B). If brightness is below 90, each channel
 * is boosted by 100 (clamped to 255).
 *
 * @param {string} rgb - CSS rgb() string, e.g. "rgb(20, 10, 50)".
 * @returns {string} Original or brightened rgb() string.
 */
function ensureReadable(rgb) {
  const m = rgb.match(/\d+/g);
  if (!m) return rgb;
  let [r, g, b] = m.map(Number);
  const brightness = (r * 299 + g * 587 + b * 114) / 1000;
  if (brightness < 90) {
    r = Math.min(255, r + 100);
    g = Math.min(255, g + 100);
    b = Math.min(255, b + 100);
    return `rgb(${r}, ${g}, ${b})`;
  }
  return rgb;
}

/**
 * Apply an accent colour to all themed UI elements.
 *
 * Updates backgrounds, borders, and text colours across the Spotify box,
 * calendar, dual clock box, clock 1 border, weather box, and date box.
 * Optionally animates the change with a CSS transition.
 *
 * @param {string}  color      - CSS colour string to apply.
 * @param {boolean} transition - Whether to animate the colour change.
 */
function applyAccent(color, transition = true) {
  color = ensureReadable(color);
  setAccentVar(color);

  const spotify    = $(SELECTORS.spotifyBox);
  const calendarBox = $(SELECTORS.calendarBox);
  const dualBox    = $(SELECTORS.dualBox);
  const clock1Box  = $(SELECTORS.clock1Box);
  const weatherBox = $(SELECTORS.weatherBox);
  const dateBox    = $(SELECTORS.dateBox);

  const ts = transition ? "background 2s ease, border-color 1s ease" : "none";

  if (spotify) {
    spotify.style.transition  = ts;
    spotify.style.background  = `linear-gradient(135deg, ${color} 0%, #1c1c1c 100%)`;
  }
  if (calendarBox) {
    calendarBox.style.transition  = ts;
    calendarBox.style.borderLeft  = `3px solid ${color}`;
    // Recolour calendar header cells and day cells
    $$("#calendar th").forEach(th => th.style.color = color);
    $$("#calendar td").forEach(td => {
      td.style.color = td.classList.contains("today") ? "#111" : color;
    });
  }
  if (dualBox)    { dualBox.style.transition    = ts; dualBox.style.borderBottom    = `2px solid ${color}`; }
  if (clock1Box)  { clock1Box.style.transition  = ts; clock1Box.style.borderRight   = `1px solid ${color}`; }
  if (weatherBox) { weatherBox.style.transition = ts; weatherBox.style.borderTop    = `2px solid ${color}`; }
  if (dateBox)    { dateBox.style.transition    = ts; dateBox.style.borderTop       = `2px solid ${color}`; }
}

/**
 * Generate a random pastel colour in HSL space.
 *
 * Saturation is 70–80%, lightness 80–90%, giving colours that are bright
 * and colourful but not fully saturated. Suitable for accenting a dark UI.
 *
 * @returns {string} HSL colour string, e.g. "hsl(210, 75%, 85%)".
 */
function randomPastel() {
  const hue   = Math.floor(Math.random() * 360);
  const sat   = 70 + Math.random() * 10;
  const light = 80 + Math.random() * 10;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

/**
 * Start the hourly ambient accent colour cycle.
 *
 * Applies a random pastel immediately (no transition on startup to avoid
 * a flash) then schedules a new pastel every hour with a smooth transition.
 * Guards against duplicate timers — does nothing if already running.
 */
function startAccentColorCycle() {
  if (state.spotify.accentTimer) return;
  applyAccent(randomPastel(), false);
  state.spotify.accentTimer = setInterval(
    () => applyAccent(randomPastel(), true),
    60 * 60 * 1000
  );
}

/**
 * Stop the ambient accent colour cycle.
 *
 * Called when Spotify starts playing so the album-art-derived accent
 * takes over without being overwritten by the hourly pastel timer.
 */
function stopAccentColorCycle() {
  if (state.spotify.accentTimer) {
    clearInterval(state.spotify.accentTimer);
    state.spotify.accentTimer = null;
  }
}

/**
 * Fetch current Spotify playback state and update the UI.
 *
 * Called every `INTERVALS.SPOTIFY` ms. Skips the update if the device
 * is offline (`state.online === false`).
 *
 * Key behaviours:
 *   - No data / not playing: starts ambient cycle and shows calendar.
 *   - Paused: sets a 30 s grace timer; if not resumed, transitions to
 *     calendar view and restarts ambient cycle.
 *   - Track change: fades out album art and track info, updates content,
 *     fades back in, then derives a new accent from the new album art.
 *   - First track seen: sets album art and derives accent immediately.
 *   - Resumed same track: re-derives accent from current album art.
 *   - Progress bar updated on every tick.
 *
 * @async
 * @returns {Promise<void>}
 */
export async function updateSpotify() {
  if (!state.online) return;

  const data = await fetchJson(PATHS.SPOTIFY);
  if (!data) {
    startAccentColorCycle();
    showCalendar();
    return;
  }

  // Normalise field names for resilience against minor API changes
  const isPlaying = !!data.isPlaying;
  const trackId   = data.trackId  || data.track  || null;
  const name      = data.track    || data.title  || "";
  const artist    = data.artist   || data.artists || "";
  const albumArt  = data.albumArt || data.album_art || null;
  const liked     = !!data.liked;
  const duration  = data.duration || data.duration_ms  || 0;
  const progress  = data.progress || data.progress_ms  || 0;

  const statusEl = $(SELECTORS.trackStatus);
  const albumEl  = $(SELECTORS.albumCover);
  const nameEl   = $(SELECTORS.trackName);
  const artistEl = $(SELECTORS.trackArtist);
  const likedEl  = $(SELECTORS.liked);
  const barEl    = $(SELECTORS.progressBar);

  // Update play/pause icon to reflect current state
  if (statusEl) statusEl.innerHTML = isPlaying ? pauseSVG : playSVG;

  const wasPlaying = state.panels.spotifyPlaying;
  const resumed    = !wasPlaying && isPlaying && trackId === state.spotify.lastTrackId;

  if (!isPlaying) {
    // Paused: start grace period before hiding the Spotify panel
    if (!state.spotify.wasPaused) {
      state.spotify.wasPaused = true;
      if (!state.spotify.hideTimeout) {
        state.spotify.hideTimeout = setTimeout(() => {
          state.spotify.hideTimeout = null;
          stopAccentColorCycle();
          applyAccent(randomPastel(), true);
          startAccentColorCycle();
          showCalendar();
        }, 30000); // 30 s grace period
      }
    }
  } else {
    // Playing: cancel any pending hide timer
    state.spotify.wasPaused = false;
    if (state.spotify.hideTimeout) {
      clearTimeout(state.spotify.hideTimeout);
      state.spotify.hideTimeout = null;
    }
    stopAccentColorCycle();
  }

  // Re-derive accent from album art when resuming the same track
  if (resumed) {
    onceImgLoaded(albumEl, () => applyAccentFromImage(albumEl, true));
  }

  // Track changed: fade out → update → fade in → new accent
  if (state.spotify.lastTrackId && trackId && state.spotify.lastTrackId !== trackId) {
    albumEl?.classList.add("fade-out");
    $(SELECTORS.spotifyBox)?.querySelector(".track-info")?.classList.add("fade-out");

    setTimeout(() => {
      if (albumArt && albumEl)  albumEl.src          = albumArt;
      if (nameEl)   nameEl.textContent               = name   || "No track";
      if (artistEl) artistEl.textContent             = artist || "Unknown";

      if (albumEl) {
        albumEl.onload = () => {
          albumEl.classList.remove("fade-out");
          albumEl.classList.add("fade-in");
          const ti = $(SELECTORS.spotifyBox)?.querySelector(".track-info");
          ti?.classList.remove("fade-out");
          ti?.classList.add("fade-in");
          setTimeout(() => {
            albumEl.classList.remove("fade-in");
            ti?.classList.remove("fade-in");
          }, 600);
          applyAccentFromImage(albumEl, true);
        };
      }
    }, 300); // wait for fade-out before swapping content
  }

  // First track ever seen: set art directly and derive accent
  if (!state.spotify.lastTrackId && trackId) {
    if (albumArt && albumEl) {
      albumEl.crossOrigin = "anonymous";
      albumEl.src         = albumArt;
      albumEl.onload = () => {
        if (isPlaying) applyAccentFromImage(albumEl, true);
        else           applyAccent(randomPastel(), true);
      };
    }
    if (nameEl)   nameEl.textContent   = name   || "No track";
    if (artistEl) artistEl.textContent = artist || "Unknown";
  }

  state.spotify.lastTrackId = trackId;

  // Always update text (handles in-place updates like title corrections)
  if (nameEl)   nameEl.textContent   = name   || "No track";
  if (artistEl) artistEl.textContent = artist || "Unknown";
  if (likedEl)  likedEl.style.display = liked ? "block" : "none";

  // Update progress bar as a percentage
  if (barEl && duration && progress !== undefined) {
    barEl.style.width = `${(progress / duration) * 100}%`;
  }

  // Update panel layout when playback is active
  if (isPlaying) {
    setCalendarOpacity(1);
    updatePanelState({ calendarFullOpacity: false, spotifyPlaying: true });
    const spotifyBox  = $(SELECTORS.spotifyBox);
    const calendarBox = $(SELECTORS.calendarBox);
    calendarBox?.classList.add("hidden");
    calendarBox?.classList.remove("visible");
    spotifyBox?.classList.remove("hidden");
    spotifyBox?.classList.add("visible");
  }
}

/**
 * Sample the dominant colour from an album art image and apply it as accent.
 *
 * Draws the image onto an off-screen canvas and samples every 40th pixel
 * (for performance). Pixels that are near-black (<30 brightness) or
 * near-white (>220 brightness) are skipped. The remaining pixels are
 * quantised into 10-unit colour buckets and the most frequent bucket
 * is selected as the dominant colour.
 *
 * Falls back to the last known accent colour on any canvas/CORS error.
 *
 * @param {HTMLImageElement} img        - The loaded album art image element.
 * @param {boolean}          transition - Whether to animate the accent change.
 */
function applyAccentFromImage(img, transition) {
  try {
    const c   = document.createElement("canvas");
    const ctx = c.getContext("2d");
    c.width   = img.naturalWidth  || img.width;
    c.height  = img.naturalHeight || img.height;
    ctx.drawImage(img, 0, 0, c.width, c.height);

    const data   = ctx.getImageData(0, 0, c.width, c.height).data;
    const counts = {};

    for (let i = 0; i < data.length; i += 40) {
      const r  = data[i], g = data[i + 1], b = data[i + 2];
      const br = (r + g + b) / 3;

      // Skip near-black and near-white pixels
      if (br < 30 || br > 220) continue;

      // Quantise to 10-unit buckets to group similar colours
      const key = `${Math.floor(r / 10)},${Math.floor(g / 10)},${Math.floor(b / 10)}`;
      counts[key] = (counts[key] || 0) + 1;
    }

    // Find the most frequent colour bucket
    let max    = 0;
    let winner = "50,50,50";
    for (const k in counts) {
      if (counts[k] > max) { max = counts[k]; winner = k; }
    }

    const [r, g, b] = winner.split(",").map(v => v * 10);
    applyAccent(`rgb(${r}, ${g}, ${b})`, transition);

  } catch {
    // CORS or canvas error — keep the current accent
    applyAccent(state.spotify.currentAccent || "rgb(50, 50, 50)", transition);
  }
}