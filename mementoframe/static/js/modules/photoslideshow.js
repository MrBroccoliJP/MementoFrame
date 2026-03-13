/*
 * MementoFrame - Raspberry Pi Smart Photo Frame
 * Copyright (c) 2026 João Fernandes
 *
 * This work is licensed under the Creative Commons Attribution-NonCommercial
 * 4.0 International License. To view a copy of this license, visit:
 * http://creativecommons.org/licenses/by-nc/4.0/
 */

/**
 * @file photoslideshow.js
 * @description Photo slideshow and burst animation module.
 *
 * Manages the full-screen photo slideshow displayed in the left panel:
 *
 *   SLIDESHOW — Photos from `window.photos` (injected by photos.js) are
 *   shuffled and displayed one at a time. Each photo cross-fades in over
 *   the previous one. Images are classified as "vertical" or "horizontal"
 *   so CSS can apply appropriate sizing (cover vs contain).
 *
 *   BURST — Every 36 slides the panel performs a burst: all thumbnail
 *   images animate upward from the bottom of the panel simultaneously,
 *   then the list is re-shuffled and the slideshow restarts from index 0.
 *   This gives a periodic visual flourish and avoids a predictable loop.
 *
 *   PRELOADING — All thumbnails are preloaded into a hidden off-screen div
 *   on startup so the burst animation is instant. The next full-size slide
 *   is also preloaded one step ahead to minimise flash on transition.
 *
 * Photo paths are constructed using `PATHS.PHOTOS_FULL` and
 * `PATHS.PHOTOS_THUMBS` from constants.js.
 */

import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, $$ } from "../utils.js";

/**
 * Initialise the photo slideshow.
 *
 * Reads `window.photos` (set globally by photos.js, served at
 * /userdata/Photos/photos.js), shuffles the list, and displays the first
 * photo immediately. Starts the slideshow interval and preloads all
 * thumbnails for the burst animation.
 *
 * Should be called once during app startup after photos.js has loaded.
 */
export function initPhotos() {
  const list = Array.isArray(window.photos) ? window.photos.slice() : [];
  state.photos.shuffled = shuffle(list);
  state.photos.index    = 0;

  showPhoto(state.photos.index);
  preloadAllThumbs();

  setInterval(showNextSlide, INTERVALS.PHOTOS);
}

/**
 * Fisher-Yates shuffle — returns a new randomly ordered array.
 *
 * @param {Array} arr - The array to shuffle.
 * @returns {Array} A new array with elements in random order.
 */
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

/**
 * Load and cross-fade a photo into the slideshow container.
 *
 * Creates a new `<img>` element and sets its src to the full-size photo
 * path. Once loaded:
 *   1. Adds "vertical" or "horizontal" class based on natural dimensions.
 *   2. Appends the image to the container.
 *   3. Forces a reflow so the browser registers the element before
 *      the CSS transition starts.
 *   4. Uses two nested `requestAnimationFrame` calls to add the "active"
 *      class (which triggers the CSS fade-in) on the very next paint.
 *   5. Removes the previously active image after 2.1 seconds (matching
 *      the CSS transition duration) to keep the DOM clean.
 *
 * Also preloads the *next* photo in the shuffled list to reduce flash.
 *
 * @param {number} index - Index into `state.photos.shuffled`.
 */
function showPhoto(index) {
  const container = $(SELECTORS.photoContainer);
  if (!container || !state.photos.shuffled.length) return;

  const name = state.photos.shuffled[index];
  const img  = new Image();
  img.src    = `${PATHS.PHOTOS_FULL}${name}`;

  img.onload = () => {
    // Classify orientation for CSS sizing rules
    if (img.naturalHeight > img.naturalWidth) {
      img.classList.add("vertical");
      img.classList.remove("horizontal");
    } else {
      img.classList.add("horizontal");
      img.classList.remove("vertical");
    }

    container.appendChild(img);

    // Force reflow so the browser paints the image before the transition
    // eslint-disable-next-line no-unused-expressions
    img.offsetHeight;

    requestAnimationFrame(() => {
      const current = container.querySelector("img.active");
      if (current) current.classList.remove("active");
      requestAnimationFrame(() => img.classList.add("active"));
    });

    // Clean up old images after the fade transition completes
    setTimeout(() => {
      const all = $$(".photo img", container);
      all.slice(0, -1).forEach(n => n.remove());
    }, 2100);
  };

  // Preload the next slide while the current one is displayed
  const next = state.photos.shuffled[index + 1];
  if (next) {
    const preload = new Image();
    preload.src   = `${PATHS.PHOTOS_FULL}${next}`;
  }
}

/**
 * Advance to the next slide, or trigger a burst every 36 slides.
 *
 * On every 36th slide (index % 36 === 0 after increment):
 *   - Clears the container.
 *   - Runs the burst animation (all thumbnails fly up).
 *   - Resets index to 0 and re-shuffles the list for the next cycle.
 *
 * Otherwise simply calls `showPhoto` with the incremented index.
 */
function showNextSlide() {
  if (!state.photos.shuffled.length) return;
  state.photos.index = (state.photos.index + 1) % state.photos.shuffled.length;

  if (state.photos.index % 36 === 0) {
    const container = $(SELECTORS.photoContainer);
    if (container) container.innerHTML = "";
    burstPhotos();
    state.photos.index    = 0;
    state.photos.shuffled = shuffle([...state.photos.shuffled]);
    return;
  }

  showPhoto(state.photos.index);
}

/**
 * Preload all thumbnail images into a hidden off-screen container.
 *
 * Runs once on init. Stores the container reference in
 * `state.photos.thumbsContainer` to avoid creating duplicates.
 * Each thumbnail is stored with `data-filename` so `burstPhotos`
 * can clone them by name without re-fetching.
 */
function preloadAllThumbs() {
  if (state.photos.thumbsContainer) return;

  const div         = document.createElement("div");
  div.style.display = "none";
  (document.body || document.documentElement).appendChild(div);
  state.photos.thumbsContainer = div;

  (window.photos || []).forEach(filename => {
    const img           = new Image();
    img.src             = `${PATHS.PHOTOS_THUMBS}${filename}`;
    img.dataset.filename = filename;
    div.appendChild(img);
  });
}

/**
 * Animate all thumbnail photos flying upward from the bottom of the left panel.
 *
 * Clears any existing floating photos, then clones each cached thumbnail
 * from `state.photos.thumbsContainer` and positions it in a grid layout
 * starting from the bottom of the panel. Each clone has the CSS class
 * "floating-photo" which drives the upward animation.
 *
 * Layout:
 *   - `photosPerRow` columns, each thumb width = panel width / photosPerRow.
 *   - Rows stack downward from the bottom (bottom offset increases per row).
 *   - If panels are swapped and the panel is not in narrow mode, a
 *     horizontal offset is applied so photos appear within the correct
 *     panel area on screen.
 *
 * Each photo removes itself from the DOM when its CSS animation ends.
 *
 * @exports burstPhotos
 */
function burstPhotos() {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;

  // Remove any leftover floating photos from a previous burst
  panel.querySelectorAll(".floating-photo").forEach(el => el.remove());

  preloadAllThumbs();

  const photosPerRow = 7;
  const panelWidth   = panel.clientWidth;
  const thumbWidth   = Math.min(100, panelWidth / photosPerRow);
  const gap          = 10;

  // Offset photos rightward if panels are swapped and not in narrow mode
  let horizontalOffset = 0;
  if (!state.panels.calendarFullOpacity && !state.panels.spotifyPlaying) {
    horizontalOffset = state.panels.swapped ? window.innerWidth * 0.3 : 0;
  }

  (window.photos || []).forEach((filename, idx) => {
    const cached = state.photos.thumbsContainer.querySelector(`img[data-filename="${filename}"]`);
    if (!cached) return;

    const img = cached.cloneNode();
    img.classList.add("floating-photo");

    const row = Math.floor(idx / photosPerRow);
    const col = idx % photosPerRow;

    img.style.width  = `${thumbWidth - gap}px`;
    img.style.left   = `${col * thumbWidth + horizontalOffset}px`;
    img.style.bottom = `${row * (120 + gap)}px`;

    panel.appendChild(img);

    // Self-remove when the CSS fly-up animation completes
    img.addEventListener("animationend", () => img.remove());
  });
}

export { burstPhotos };