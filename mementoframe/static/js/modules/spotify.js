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
 * This version is optimised for Raspberry Pi-class devices:
 *   - Album art is preloaded and decoded off-DOM before the visible <img> changes.
 *   - The visible art swap and accent update happen in the same animation frame.
 *   - Rapid song switching is cancellation-safe via a render sequence token.
 *   - Colour extraction uses a cheap 48x48 atmosphere/hue-family algorithm instead
 *     of expensive full-image quantisation.
 *   - Grayscale covers stay grayscale; saturation is never forced onto neutral art.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, $$, fetchJson } from "../utils.js";
import { showCalendar, setCalendarOpacity, updatePanelState } from "./layout.js";

/** SVG markup for the play button icon. */
const playSVG  = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M3 22v-20l18 10-18 10z"/></svg>`;

/** SVG markup for the pause button icon. */
const pauseSVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M6 2h4v20h-4zm8 0h4v20h-4z"/></svg>`;

// ─── Render State ───────────────────────────────────────────────────────────
// Every artwork render receives a unique sequence number. If a newer track
// starts loading, older image loads / timeouts / colour calculations are ignored.
let spotifyRenderSeq = 0;
let spotifyRenderTimer = null;
let spotifyFadeCleanupTimer = null;
let lastRenderedArtworkKey = null;
let lastRequestedArtworkKey = null;
let lastPreloadedArtworkKey = null;

// ─── Public Init ────────────────────────────────────────────────────────────

/**
 * Initialise Spotify polling and the ambient accent colour cycle.
 */
export function initSpotify() {
  startAccentColorCycle();
  startSpotifyPolling(INTERVALS.SPOTIFY);
}

/**
 * Start (or restart) the Spotify polling interval.
 *
 * @param {number} ms - Polling interval in milliseconds.
 */
function startSpotifyPolling(ms) {
  if (state.spotify.pollTimer) clearInterval(state.spotify.pollTimer);
  state.spotify.pollTimer = setInterval(updateSpotify, ms);
  updateSpotify();
}

// ─── Accent Application ─────────────────────────────────────────────────────

/**
 * Write an accent colour to the CSS custom property and state.
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
 * Keeps neutral colours neutral; it never invents hue/saturation.
 *
 * @param {string} rgb - CSS rgb() string, e.g. "rgb(20, 10, 50)".
 * @returns {string} Original or brightened rgb() string.
 */
function ensureReadable(color) {
  if (typeof color !== "string") return color;

  const value = color.trim();

  // Do not parse hsl(...) as rgb(...).
  // Browser can use HSL directly, and your randomColor() already returns light colours.
  if (value.startsWith("hsl")) {
    return value;
  }

  // Spotify album-art extraction returns rgb(...), so keep supporting rgb/rgba.
  const m = value.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i);
  if (!m) return color;

  let r = Number(m[1]);
  let g = Number(m[2]);
  let b = Number(m[3]);

  if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) {
    return color;
  }

  const brightness = perceivedBrightness({ r, g, b });

  if (brightness < 90) {
    const amount = 90 - brightness;
    r = Math.min(255, r + amount);
    g = Math.min(255, g + amount);
    b = Math.min(255, b + amount);
  }

  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

/**
 * Apply an accent colour to all themed UI elements.
 *
 * @param {string}  color      - CSS colour string to apply.
 * @param {boolean} transition - Whether to animate the colour change.
 */
function applyAccent(color, transition = true) {
  color = ensureReadable(color);
  setAccentVar(color);

  const spotify     = $(SELECTORS.spotifyBox);
  const calendarBox = $(SELECTORS.calendarBox);
  const dualBox     = $(SELECTORS.dualBox);
  const clock1Box   = $(SELECTORS.clock1Box);
  const weatherBox  = $(SELECTORS.weatherBox);
  const dateBox     = $(SELECTORS.dateBox);

  const ts = transition
    ? "background 1s ease, border-color 1s ease, color 1s ease"
    : "none";

  if (spotify) {
    spotify.style.transition = ts;
    spotify.style.background = `linear-gradient(135deg, ${color} 0%, #1c1c1c 100%)`;
  }

  if (calendarBox) {
    calendarBox.style.transition = ts;
    calendarBox.style.borderLeft = `3px solid ${color}`;

    $$("#calendar th").forEach(th => {
      th.style.color = color;
    });

    $$("#calendar td").forEach(td => {
      td.style.color = td.classList.contains("today") ? "#111" : color;
    });
  }

  if (dualBox)    { dualBox.style.transition    = ts; dualBox.style.borderBottom = `2px solid ${color}`; }
  if (clock1Box)  { clock1Box.style.transition  = ts; clock1Box.style.borderRight  = `1px solid ${color}`; }
  if (weatherBox) { weatherBox.style.transition = ts; weatherBox.style.borderTop   = `2px solid ${color}`; }
  if (dateBox)    { dateBox.style.transition    = ts; dateBox.style.borderTop      = `2px solid ${color}`; }
}

/**
 * Generate a random color colour in HSL space.
 *
 * @returns {string} HSL colour string.
 */
function randomColor() {
  const hue   = Math.floor(Math.random() * 360);
  const sat   = 55 + Math.floor(Math.random() * 20);   // 55–75%
  const light = 45 + Math.floor(Math.random() * 20);   // 45–65%
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

/**
 * Start the hourly ambient accent colour cycle.
 */
function startAccentColorCycle() {
  if (state.spotify.accentTimer) return;

  applyAccent(randomColor(), false);
  state.spotify.accentTimer = setInterval(
    () => applyAccent(randomColor(), true),
    30*60*1000
  );
}

/**
 * Stop the ambient accent colour cycle.
 */
function stopAccentColorCycle() {
  if (state.spotify.accentTimer) {
    clearInterval(state.spotify.accentTimer);
    state.spotify.accentTimer = null;
  }
}

// ─── Spotify Polling / Rendering ────────────────────────────────────────────

/**
 * Show the Spotify panel and hide the calendar panel.
 * Used after the first album art + accent are ready, so the placeholder
 * does not flash before the real cover appears.
 */
function showSpotifyPanelNow() {
  setCalendarOpacity(1);
  updatePanelState({ calendarFullOpacity: false, spotifyPlaying: true });

  const spotifyBox  = $(SELECTORS.spotifyBox);
  const calendarBox = $(SELECTORS.calendarBox);

  calendarBox?.classList.add("hidden");
  calendarBox?.classList.remove("visible");

  spotifyBox?.classList.remove("hidden");
  spotifyBox?.classList.add("visible");
}


/**
 * Fetch current Spotify playback state and update the UI.
 *
 * @async
 * @returns {Promise<void>}
 */
export async function updateSpotify() {
  if (!state.online) return;

  const data = await fetchJson(PATHS.SPOTIFY);

  if (!data) {
    cancelArtworkRender({ clearClasses: true });
    startAccentColorCycle();
    showCalendar();
    return;
  }

  // Normalise field names for resilience against minor API changes.
  const isPlaying = !!data.isPlaying;
  const trackId   = data.trackId  || data.trackIdSpotify || data.id || data.track || null;
  const name      = data.track    || data.title  || "";
  const artist    = data.artist   || data.artists || "";
  const albumArt  = data.albumArt || data.album_art || null;
  const liked     = !!data.liked;
  const duration  = data.duration || data.duration_ms || 0;
  const progress  = data.progress || data.progress_ms || 0;

  const statusEl = $(SELECTORS.trackStatus);
  const albumEl  = $(SELECTORS.albumCover);
  const nameEl   = $(SELECTORS.trackName);
  const artistEl = $(SELECTORS.trackArtist);
  const likedEl  = $(SELECTORS.liked);
  const barEl    = $(SELECTORS.progressBar);

  if (statusEl) statusEl.innerHTML = isPlaying ? pauseSVG : playSVG;

  // Text and progress update immediately. This prevents the Spotify panel from
  // appearing empty while artwork/colour extraction is still in flight.
  if (nameEl)   nameEl.textContent   = name   || "No track";
  if (artistEl) artistEl.textContent = artist || "Unknown";
  if (likedEl)  likedEl.style.display = liked ? "block" : "none";

  if (barEl && duration && progress !== undefined) {
    barEl.style.width = `${Math.max(0, Math.min(100, (progress / duration) * 100))}%`;
  }

  const previousTrackId = state.spotify.lastTrackId;
  const trackChanged = !!trackId && !!previousTrackId && trackId !== previousTrackId;
  const firstTrack = !!trackId && !previousTrackId;
  const artworkKey = albumArt ? `${trackId || "unknown"}|${albumArt}` : null;

  if (!isPlaying) {
    if (!state.spotify.wasPaused) {
      state.spotify.wasPaused = true;

      if (!state.spotify.hideTimeout) {
        state.spotify.hideTimeout = setTimeout(() => {
          state.spotify.hideTimeout = null;
          cancelArtworkRender({ clearClasses: true });
          stopAccentColorCycle();
          applyAccent(randomColor(), true);
          startAccentColorCycle();
          showCalendar();
        }, 30000);
      }
    }
  } else {
    state.spotify.wasPaused = false;

    if (state.spotify.hideTimeout) {
      clearTimeout(state.spotify.hideTimeout);
      state.spotify.hideTimeout = null;
    }

    stopAccentColorCycle();
  }

  const spotifyBox = $(SELECTORS.spotifyBox);
  const spotifyAlreadyVisible = spotifyBox?.classList.contains("visible");

  const needsArtworkRender =
    isPlaying &&
    artworkKey &&
    artworkKey !== lastRenderedArtworkKey &&
    artworkKey !== lastRequestedArtworkKey;

  const revealSpotifyAfterArtwork =
    needsArtworkRender && !spotifyAlreadyVisible;

  if (isPlaying && !revealSpotifyAfterArtwork) {
    showSpotifyPanelNow();
  }

  // Only render artwork/colour when the artwork actually changes. This avoids
  // repeated canvas work on every poll, which matters on Raspberry Pi 3.
  if (needsArtworkRender) {
    renderArtworkAndAccent({
      albumArt,
      albumEl,
      artworkKey,
      transition: true,
      fade: spotifyAlreadyVisible && trackChanged,
      revealWhenReady: revealSpotifyAfterArtwork,
    });
  }

  // First paused track: preload the image for display, but keep ambient colour.
  if (!isPlaying && firstTrack && albumArt && albumEl && artworkKey !== lastPreloadedArtworkKey) {
    renderArtworkOnly({ albumArt, albumEl, artworkKey });
  }

  state.spotify.lastTrackId = trackId;
}

/**
 * Cancel any in-flight artwork render. Old async work is invalidated because
 * the sequence number is incremented.
 *
 * @param {{ clearClasses?: boolean }} options
 */
function cancelArtworkRender({ clearClasses = false } = {}) {
  spotifyRenderSeq++;
  lastRequestedArtworkKey = null;

  if (spotifyRenderTimer) {
    clearTimeout(spotifyRenderTimer);
    spotifyRenderTimer = null;
  }

  if (spotifyFadeCleanupTimer) {
    clearTimeout(spotifyFadeCleanupTimer);
    spotifyFadeCleanupTimer = null;
  }

  if (clearClasses) {
    const albumEl = $(SELECTORS.albumCover);
    const trackInfoEl = $(SELECTORS.spotifyBox)?.querySelector(".track-info");
    albumEl?.classList.remove("fade-out", "fade-in");
    trackInfoEl?.classList.remove("fade-out", "fade-in");
  }
}

/**
 * Preload and decode an image without changing the visible album art element.
 *
 * @param {string} src
 * @returns {Promise<HTMLImageElement>}
 */
function preloadImage(src) {
  return new Promise((resolve, reject) => {
    if (!src) {
      reject(new Error("Missing image src"));
      return;
    }

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.decoding = "async";

    img.onload = async () => {
      try {
        if (img.decode) await img.decode();
      } catch {
        // Some browsers reject decode() even after load; the image is still usable.
      }

      resolve(img);
    };

    img.onerror = () => reject(new Error(`Failed to load image: ${src}`));

    // Handlers and crossOrigin must be set before src to avoid cache/onload races.
    img.src = src;
  });
}

/**
 * Swap the visible album image to an already-loaded image.
 *
 * @param {HTMLImageElement|null} albumEl
 * @param {HTMLImageElement} loadedImg
 */
function setAlbumImageNow(albumEl, loadedImg) {
  if (!albumEl || !loadedImg?.src) return;
  albumEl.crossOrigin = "anonymous";
  albumEl.src = loadedImg.src;
}

/**
 * Restart fade-in animation safely.
 *
 * @param {HTMLImageElement|null} albumEl
 * @param {Element|null} trackInfoEl
 */
function restartFadeIn(albumEl, trackInfoEl) {
  if (spotifyFadeCleanupTimer) {
    clearTimeout(spotifyFadeCleanupTimer);
    spotifyFadeCleanupTimer = null;
  }

  albumEl?.classList.remove("fade-out", "fade-in");
  trackInfoEl?.classList.remove("fade-out", "fade-in");

  // Force a style flush so fade-in reliably replays on Chromium/RPi.
  void albumEl?.offsetWidth;

  albumEl?.classList.add("fade-in");
  trackInfoEl?.classList.add("fade-in");

  spotifyFadeCleanupTimer = setTimeout(() => {
    albumEl?.classList.remove("fade-in");
    trackInfoEl?.classList.remove("fade-in");
    spotifyFadeCleanupTimer = null;
  }, 600);
}

/**
 * Render album art and accent colour in a cancellation-safe way.
 *
 * @param {object} options
 * @param {string} options.albumArt
 * @param {HTMLImageElement|null} options.albumEl
 * @param {string} options.artworkKey
 * @param {boolean} options.transition
 * @param {boolean} options.fade
 * @param {boolean} options.revealWhenReady
 */
function renderArtworkAndAccent({
  albumArt,
  albumEl,
  artworkKey,
  transition = true,
  fade = true,
  revealWhenReady = false,
}) {
  spotifyRenderSeq++;
  const seq = spotifyRenderSeq;
  lastRequestedArtworkKey = artworkKey;

  if (spotifyRenderTimer) {
    clearTimeout(spotifyRenderTimer);
    spotifyRenderTimer = null;
  }

  if (spotifyFadeCleanupTimer) {
    clearTimeout(spotifyFadeCleanupTimer);
    spotifyFadeCleanupTimer = null;
  }

  const trackInfoEl = $(SELECTORS.spotifyBox)?.querySelector(".track-info");

  albumEl?.classList.remove("fade-in");
  trackInfoEl?.classList.remove("fade-in");

  if (fade && albumEl?.src) {
    albumEl?.classList.add("fade-out");
    trackInfoEl?.classList.add("fade-out");
  } else {
    albumEl?.classList.remove("fade-out");
    trackInfoEl?.classList.remove("fade-out");
  }

  const minimumFadeMs = fade && albumEl?.src ? 180 : 0;

  spotifyRenderTimer = setTimeout(async () => {
    spotifyRenderTimer = null;

    try {
      const loadedImg = await preloadImage(albumArt);
      if (seq !== spotifyRenderSeq) return;

      let color = state.spotify.currentAccent || "rgb(80, 80, 80)";

      try {
        color = getAtmosphereColorFromImage(loadedImg);
      } catch (err) {
        console.warn("Album colour extraction failed:", err);
      }

      if (seq !== spotifyRenderSeq) return;

      requestAnimationFrame(() => {
        if (seq !== spotifyRenderSeq) return;

        setAlbumImageNow(albumEl, loadedImg);
        applyAccent(color, transition);

        lastRenderedArtworkKey = artworkKey;
        lastPreloadedArtworkKey = artworkKey;
        lastRequestedArtworkKey = null;

        if (revealWhenReady) {
          showSpotifyPanelNow();
        }

        if (fade) restartFadeIn(albumEl, trackInfoEl);
        else {
          albumEl?.classList.remove("fade-out", "fade-in");
          trackInfoEl?.classList.remove("fade-out", "fade-in");
        }
      });
    } catch (err) {
      if (seq !== spotifyRenderSeq) return;

      console.warn("Album art render failed:", err);
      lastRequestedArtworkKey = null;
      albumEl?.classList.remove("fade-out", "fade-in");
      trackInfoEl?.classList.remove("fade-out", "fade-in");
      applyAccent(state.spotify.currentAccent || "rgb(80, 80, 80)", transition);

      if (revealWhenReady) {
        showSpotifyPanelNow();
      }
    }
  }, minimumFadeMs);
}

/**
 * Preload and display artwork without changing the accent colour.
 * Used for paused first-track state.
 *
 * @param {object} options
 * @param {string} options.albumArt
 * @param {HTMLImageElement|null} options.albumEl
 * @param {string} options.artworkKey
 */
async function renderArtworkOnly({ albumArt, albumEl, artworkKey }) {
  spotifyRenderSeq++;
  const seq = spotifyRenderSeq;
  lastRequestedArtworkKey = artworkKey;

  try {
    const loadedImg = await preloadImage(albumArt);
    if (seq !== spotifyRenderSeq) return;

    setAlbumImageNow(albumEl, loadedImg);
    lastPreloadedArtworkKey = artworkKey;
    lastRequestedArtworkKey = null;
  } catch (err) {
    if (seq !== spotifyRenderSeq) return;
    console.warn("Paused artwork preload failed:", err);
    lastRequestedArtworkKey = null;
  }
}

// ─── Fast Atmosphere Colour Extraction ──────────────────────────────────────

const ART_COLOR_SIZE = 48;
const HUE_BINS = 24;

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function circularBinDistance(a, b, total = HUE_BINS) {
  const d = Math.abs(a - b);
  return Math.min(d, total - d);
}

function rgbCss({ r, g, b }) {
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

function rgbToHsl(r, g, b) {
  r /= 255;
  g /= 255;
  b /= 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;

  let h = 0;
  let s = 0;

  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));

    switch (max) {
      case r:
        h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        break;
      case g:
        h = ((b - r) / d + 2) / 6;
        break;
      case b:
        h = ((r - g) / d + 4) / 6;
        break;
    }
  }

  return [h, s, l];
}

function hslToRgb(h, s, l) {
  let r;
  let g;
  let b;

  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p, q, t) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };

    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;

    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }

  return {
    r: Math.round(r * 255),
    g: Math.round(g * 255),
    b: Math.round(b * 255),
  };
}

function perceivedBrightness({ r, g, b }) {
  return (r * 299 + g * 587 + b * 114) / 1000;
}

function colorfulness({ r, g, b }) {
  return (Math.max(r, g, b) - Math.min(r, g, b)) / 255;
}

function isNearGray({ r, g, b }, tolerance = 10) {
  return (
    Math.abs(r - g) < tolerance &&
    Math.abs(g - b) < tolerance &&
    Math.abs(r - b) < tolerance
  );
}

function normaliseAtmosphereAccent(rgb) {
  let [h, s, l] = rgbToHsl(rgb.r, rgb.g, rgb.b);

  // True grayscale / near-grayscale covers should stay neutral. Do not force
  // saturation, because HSL hue is meaningless when saturation is near zero.
  if (s < 0.065 || colorfulness(rgb) < 0.075 || isNearGray(rgb, 14)) {
    const brightness = perceivedBrightness(rgb);
    const neutral = Math.round(clamp(brightness, 105, 165));
    return { r: neutral, g: neutral, b: neutral };
  }

  // Preserve the album mood, but keep it usable as a dark UI accent.
  // This intentionally stays more muted than the previous Vibrant/MMCQ approach.
  s = clamp(s * 1.08, 0.16, 0.55);
  l = clamp(l, 0.30, 0.52);

  let adjusted = hslToRgb(h, s, l);

  if (perceivedBrightness(adjusted) < 82) {
    const lift = 82 - perceivedBrightness(adjusted);
    adjusted = {
      r: clamp(adjusted.r + lift, 0, 255),
      g: clamp(adjusted.g + lift, 0, 255),
      b: clamp(adjusted.b + lift, 0, 255),
    };
  }

  return adjusted;
}

/**
 * Extract a Spotify-like "atmosphere" colour from album art.
 *
 * Instead of picking the most vibrant foreground object, this chooses the
 * dominant hue family by area, then averages that family. This tends to match
 * the visible mood of the cover better on artwork with large blue/green/gray
 * fields and smaller beige/red foreground objects.
 *
 * @param {HTMLImageElement} img
 * @returns {string} CSS rgb() colour.
 */
function getAtmosphereColorFromImage(img) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  if (!ctx) throw new Error("Canvas 2D context unavailable");

  canvas.width = ART_COLOR_SIZE;
  canvas.height = ART_COLOR_SIZE;

  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, ART_COLOR_SIZE, ART_COLOR_SIZE);

  const data = ctx.getImageData(0, 0, ART_COLOR_SIZE, ART_COLOR_SIZE).data;
  const bins = Array.from({ length: HUE_BINS }, () => 0);
  const pixels = [];

  let usableWeight = 0;
  let neutralR = 0;
  let neutralG = 0;
  let neutralB = 0;
  let neutralWeight = 0;

  // Ignore a very small outer edge. Album covers often have white/black borders,
  // and those should not define the UI colour.
  const edge = Math.round(ART_COLOR_SIZE * 0.04);

  for (let y = edge; y < ART_COLOR_SIZE - edge; y++) {
    for (let x = edge; x < ART_COLOR_SIZE - edge; x++) {
      const i = (y * ART_COLOR_SIZE + x) * 4;
      const a = data[i + 3];
      if (a < 128) continue;

      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const rgb = { r, g, b };
      const brightness = perceivedBrightness(rgb);

      if (brightness < 16 || brightness > 245) continue;

      const [h, s, l] = rgbToHsl(r, g, b);
      const chroma = colorfulness(rgb);

      // Mild centre weighting only. Too much centre weighting causes beige faces
      // or hands to beat a larger blue/green background.
      const dx = (x + 0.5) / ART_COLOR_SIZE - 0.5;
      const dy = (y + 0.5) / ART_COLOR_SIZE - 0.5;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const centerWeight = 1 + Math.max(0, 0.18 - distance) * 0.7;

      const weight = centerWeight;
      usableWeight += weight;

      const isColorPixel = s >= 0.075 && chroma >= 0.045;

      if (isColorPixel) {
        const bin = Math.floor(h * HUE_BINS) % HUE_BINS;
        const colourWeight = weight * (0.9 + clamp(s, 0, 0.65));
        bins[bin] += colourWeight;
        pixels.push({ r, g, b, h, s, l, bin, weight: colourWeight });
      } else {
        neutralR += r * weight;
        neutralG += g * weight;
        neutralB += b * weight;
        neutralWeight += weight;
      }
    }
  }

  if (!usableWeight) return "rgb(110, 110, 110)";

  const totalColourWeight = bins.reduce((sum, value) => sum + value, 0);

  // If the whole cover is basically black/white/gray, return a neutral accent.
  if (!pixels.length || totalColourWeight < usableWeight * 0.08) {
    if (neutralWeight) {
      return rgbCss(normaliseAtmosphereAccent({
        r: neutralR / neutralWeight,
        g: neutralG / neutralWeight,
        b: neutralB / neutralWeight,
      }));
    }

    return "rgb(110, 110, 110)";
  }

  // Pick dominant hue family, not single most saturated swatch. Adjacent bins are
  // grouped so a broad blue/green atmosphere wins over a small beige foreground.
  let bestBin = 0;
  let bestFamilyWeight = -1;

  for (let bin = 0; bin < HUE_BINS; bin++) {
    const familyWeight =
      bins[(bin - 1 + HUE_BINS) % HUE_BINS] * 0.7 +
      bins[bin] +
      bins[(bin + 1) % HUE_BINS] * 0.7;

    if (familyWeight > bestFamilyWeight) {
      bestFamilyWeight = familyWeight;
      bestBin = bin;
    }
  }

  // If no hue family has meaningful area, fall back to the average of all colour.
  const useAllColourPixels = bestFamilyWeight < totalColourWeight * 0.16;

  let rSum = 0;
  let gSum = 0;
  let bSum = 0;
  let weightSum = 0;

  for (const p of pixels) {
    const inFamily = circularBinDistance(p.bin, bestBin) <= 1;
    if (!useAllColourPixels && !inFamily) continue;

    // Keep the averaging area-driven. Saturation gets only a tiny bonus.
    const w = p.weight * (1 + p.s * 0.18);
    rSum += p.r * w;
    gSum += p.g * w;
    bSum += p.b * w;
    weightSum += w;
  }

  if (!weightSum) {
    for (const p of pixels) {
      rSum += p.r * p.weight;
      gSum += p.g * p.weight;
      bSum += p.b * p.weight;
      weightSum += p.weight;
    }
  }

  if (!weightSum) return "rgb(110, 110, 110)";

  const accent = normaliseAtmosphereAccent({
    r: rSum / weightSum,
    g: gSum / weightSum,
    b: bSum / weightSum,
  });

  return rgbCss(accent);
}