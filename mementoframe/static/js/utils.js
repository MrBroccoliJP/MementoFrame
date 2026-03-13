/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file utils.js
 * @description Shared utility functions used across all modules.
 *
 * All functions are pure or side-effect-free helpers with no dependency
 * on application state. They can be imported by any module without
 * introducing circular references.
 */

/**
 * Fetch a URL and parse the response as JSON.
 *
 * Always uses `cache: "no-store"` so polling endpoints (spotify.json,
 * weather.json, status.json) always return fresh data and are never
 * served from the browser cache.
 *
 * On any network or parse error, logs a warning to the console and
 * returns the provided fallback value instead of throwing.
 *
 * @async
 * @param {string} url               - The URL to fetch.
 * @param {*}      [fallback=null]   - Value to return on error.
 * @returns {Promise<*>} Parsed JSON data, or `fallback` on failure.
 */
export async function fetchJson(url, fallback = null) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn(`Fetch failed for ${url}:`, e);
    return fallback;
  }
}

/**
 * Shorthand for `document.querySelector` with an optional root element.
 *
 * @param {string}              sel          - CSS selector string.
 * @param {Element|Document}    [root=document] - Element to query within.
 * @returns {Element|null} First matching element, or null if not found.
 */
export const $ = (sel, root = document) => root.querySelector(sel);

/**
 * Shorthand for `document.querySelectorAll`, returning a real Array.
 *
 * Returns an Array (not a NodeList) so callers can use `.forEach`,
 * `.map`, `.filter`, etc. without conversion.
 *
 * @param {string}              sel          - CSS selector string.
 * @param {Element|Document}    [root=document] - Element to query within.
 * @returns {Element[]} Array of all matching elements (may be empty).
 */
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/**
 * Set an element's text content only if it has changed.
 *
 * Avoids unnecessary DOM writes and layout thrashing on elements that
 * are updated on every clock tick (e.g. the time display). Does nothing
 * if `el` is null or falsy.
 *
 * @param {Element|null} el   - The target DOM element.
 * @param {string}       text - The new text content to set.
 */
export function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

/**
 * Clamp a number to a given range.
 *
 * @param {number} n   - The value to clamp.
 * @param {number} min - Minimum allowed value (inclusive).
 * @param {number} max - Maximum allowed value (inclusive).
 * @returns {number} `n` clamped between `min` and `max`.
 */
export function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

/**
 * Call a callback once an image has fully loaded.
 *
 * If the image is already loaded (`complete` and has a non-zero natural
 * width), the callback is invoked synchronously. Otherwise it is attached
 * as a one-time `onload` handler.
 *
 * Used by spotify.js to derive the album-art accent colour only after
 * the image is available for canvas sampling.
 *
 * @param {HTMLImageElement|null} img - The image element to watch.
 * @param {Function}              cb  - Callback to invoke when loaded.
 */
export function onceImgLoaded(img, cb) {
  if (!img) return;
  if (img.complete && img.naturalWidth > 0) cb();
  else img.onload = cb;
}

/**
 * Create a debounced version of a function.
 *
 * The returned function delays invoking `fn` until `ms` milliseconds
 * have elapsed since the last call. Repeated calls within the delay
 * window reset the timer, so `fn` is only called once after the
 * activity settles.
 *
 * Used to prevent rapid file-change events from triggering multiple
 * page reloads in config.js.
 *
 * @param {Function} fn       - The function to debounce.
 * @param {number}   [ms=200] - Delay in milliseconds.
 * @returns {Function} Debounced wrapper function.
 */
export function debounce(fn, ms = 200) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}