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
  state.photos.index = 0;

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
  const img = new Image();
  img.src = `${PATHS.PHOTOS_FULL}${name}`;

  img.onload = () => {
    // Classify orientation for CSS sizing rules
    if (img.naturalHeight > img.naturalWidth) {
      img.classList.add("vertical");
      img.classList.remove("horizontal");
    } else {
      img.classList.add("horizontal");
      img.classList.remove("vertical");
    }

    const frame = document.createElement("div");
    frame.className = "photo-frame";

    if (img.classList.contains("vertical")) {
      frame.classList.add("vertical-frame");

      const aspect = img.naturalWidth / img.naturalHeight;
      frame.style.width = `${container.clientHeight * aspect}px`;
    } else {
      frame.classList.add("horizontal-frame");
    }

    frame.appendChild(img);
    container.appendChild(frame);

    // Force reflow so the browser paints the image before the transition
    // eslint-disable-next-line no-unused-expressions
    img.offsetHeight;

    requestAnimationFrame(() => {
      const current = container.querySelector(".photo-frame.active");
      if (current) current.classList.remove("active");

      requestAnimationFrame(() => frame.classList.add("active"));
    });

    // Clean up old images after the fade transition completes
    setTimeout(() => {
      const all = $$(".photo-frame", container);
      all.slice(0, -1).forEach((n) => n.remove());
    }, 2100);
  };

  // Preload the next slide while the current one is displayed
  const next = state.photos.shuffled[index + 1];
  if (next) {
    const preload = new Image();
    preload.src = `${PATHS.PHOTOS_FULL}${next}`;
  }
}

/**
 * Advance to the next slide, or trigger a burst every 36 slides.
 *
 * On every 36th slide:
 *   - Awaits burstPhotos(), which itself waits for all thumbs to load,
 *     runs the full animation, and resolves only after the last photo
 *     has flown off screen.
 *   - Only then resets the index and reshuffles, so the next slideshow
 *     cycle starts on a clean screen with no overlap.
 *
 * Otherwise simply calls showPhoto with the incremented index.
 */
async function showNextSlide() {
  if (!state.photos.shuffled.length) return;
  state.photos.index = (state.photos.index + 1) % state.photos.shuffled.length;

  if (state.photos.index % 36 === 0) {
    await burstPhotos();
    await new Promise((r) => setTimeout(r, 1000));
    state.photos.index = 0;
    state.photos.shuffled = shuffle([...state.photos.shuffled]);
    showPhoto(state.photos.index);
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
 *
 * Returns a Promise that resolves once every thumbnail has fired
 * onload or onerror, so burstPhotos() can wait for all images to
 * be decoded before starting the animation.
 *
 * @returns {Promise<void>}
 */
function preloadAllThumbs() {
  if (state.photos.thumbsContainer) return state.photos.thumbsReady;

  const div = document.createElement("div");
  div.style.display = "none";
  (document.body || document.documentElement).appendChild(div);
  state.photos.thumbsContainer = div;

  const photos = window.photos || [];
  const loads = photos.map(
    (filename) =>
      new Promise((resolve) => {
        const img = new Image();
        img.dataset.filename = filename;
        img.onload = resolve;
        img.onerror = resolve; // don't block burst on a missing thumb
        img.src = `${PATHS.PHOTOS_THUMBS}${filename}`;
        div.appendChild(img);
      }),
  );

  state.photos.thumbsReady = Promise.all(loads);
  return state.photos.thumbsReady;
}

/**
 * Animate all thumbnail photos flying upward from the bottom of the left panel.
 *
 * Waits for all thumbnails to be decoded (via state.photos.thumbsReady) before
 * starting, so the burst never begins with blank images.
 *
 * Timing is driven by a constant speed (SPEED_VH_PER_MS) rather than a fixed
 * duration. Every photo travels the same distance at the same speed, so the
 * animation always looks the same regardless of photo count. ROW_STAGGER is a
 * fixed aesthetic delay between rows launching — it doesn't affect individual
 * photo speed. The returned Promise resolves when the last photo's animationend
 * fires, after which the caller waits 1 second before starting the next cycle.
 *
 * Returns a Promise that resolves only after the last photo's animationend fires,
 * so callers can await the full burst before starting the next slideshow cycle.
 *
 * Layout:
 *   - `photosPerRow` columns, each thumb width = panel width / photosPerRow.
 *   - Partial final rows are centred horizontally rather than left-aligned.
 *   - If panels are swapped and not in narrow mode, a horizontal offset keeps
 *     photos within the correct panel area.
 *
 * @async
 * @returns {Promise<void>} Resolves when the last floating photo leaves the screen.
 * @exports burstPhotos
 */
async function burstPhotos() {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;

  // Wait for all thumbs to be decoded before touching the DOM
  await preloadAllThumbs();

  // Remove leftover floating photos from any previous burst
  panel.querySelectorAll(".floating-photo").forEach((el) => el.remove());

  // Clear the static slideshow image now — thumbs are ready so there's
  // no black gap; the first row of floating photos is about to paint.
  const container = $(SELECTORS.photoContainer);
  if (container) container.innerHTML = "";

  const photos = window.photos || [];
  if (!photos.length) return;

  const photosPerRow = 6;
  const gap = 8;
  // Always lay out within the narrow panel width (69%) regardless of current
  // panel state — the burst should never draw into the right panel area.
  const NARROW_WIDTH = Math.floor(window.innerWidth * 0.69);
  const panelWidth = Math.min(panel.clientWidth, NARROW_WIDTH);
  const thumbWidth = Math.floor(panelWidth / photosPerRow);

  // Thumb height: use a fixed aspect ratio (4:3) since images vary.
  // This is what determines the vertical spacing between rows.
  const thumbHeight = Math.round(thumbWidth * 0.75);
  const rowSpacing = thumbHeight + gap;

  const totalRows = Math.ceil(photos.length / photosPerRow);

  // Constant speed: every photo travels at the same velocity.
  // The keyframe moves each photo -200vh upward. Starting position (bottom)
  // adds extra distance for lower rows, but duration is set for the worst-case
  // first row so all rows clear the top at a consistent speed.
  const vh = window.innerHeight;
  const SPEED_PX_MS = 0.4; // px per ms — tune to change speed

  // Track the very last photo element so we can await its animationend
  let lastImg = null;

  photos.forEach((filename, idx) => {
    const cached = state.photos.thumbsContainer?.querySelector(
      `img[data-filename="${filename}"]`,
    );
    if (!cached) return;

    const img = cached.cloneNode(true);
    img.classList.add("floating-photo");

    const row = Math.floor(idx / photosPerRow);
    const col = idx % photosPerRow;

    // Centre the partial final row
    const isLastRow = row === totalRows - 1;
    const countInRow = isLastRow
      ? photos.length % photosPerRow || photosPerRow
      : photosPerRow;
    const rowOffset = isLastRow
      ? Math.floor((photosPerRow - countInRow) / 2) * thumbWidth
      : 0;

    // Pre-position each row physically below the screen by its row index.
    // Row 0 starts just below the bottom edge; row 1 one row-height further
    // down; etc. All photos animate at the same speed with no delay, so they
    // naturally arrive sequentially without ever occupying the same space.
    const startBelow = thumbHeight + row * rowSpacing;
    const travelPx = vh + startBelow + 40;
    const animDuration = Math.round(travelPx / SPEED_PX_MS);

    img.style.width = `${thumbWidth - gap}px`;
    img.style.height = `${thumbHeight}px`;
    const baseLeft = col * thumbWidth + rowOffset;
    img.style.left = `calc(${baseLeft}px + var(--burst-x-offset, 0px))`;
    img.style.bottom = `-${startBelow}px`;
    img.style.setProperty("--burst-travel", `${travelPx}px`);
    img.style.animationDuration = `${animDuration}ms`;
    img.style.animationDelay = "0ms";

    panel.appendChild(img);
    img.addEventListener("animationend", () => img.remove(), { once: true });

    lastImg = img;
  });

  // Resolve only after the last photo has fully left the screen
  if (lastImg) {
    await new Promise((resolve) =>
      lastImg.addEventListener("animationend", resolve, { once: true }),
    );
  }
}

//debug function to trigger the burst manually without waiting for the slideshow cycle
async function runBurstCycle() {
  await burstPhotos();
  await new Promise((r) => setTimeout(r, 1000));

  state.photos.index = 0;
  state.photos.shuffled = shuffle([...state.photos.shuffled]);

  showPhoto(state.photos.index);
}

export { burstPhotos, runBurstCycle };
