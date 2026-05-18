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

let photosTimer = null;
let slideAdvanceRunning = false;

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

  photosTimer = setInterval(showNextSlide, INTERVALS.PHOTOS);
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

      // Width is fixed — the frame never changes size.
      // Zoom is achieved by scaleX() on the frame itself; transform-origin is
      // center (default) so it grows symmetrically from the pinned centre point.
      // translateX(-50%) in CSS composes with scaleX() cleanly — the browser
      // applies the full transform list left-to-right, so centering is preserved.
      const aspect    = img.naturalWidth / img.naturalHeight;
      const baseWidth = Math.round(container.clientHeight * aspect);

      frame.style.width      = `${baseWidth}px`;
      frame.style.transition = `opacity 2s ease-in-out, left 1.2s cubic-bezier(0.4,0,0.2,1), transform 15s ease-in-out`;
      frame.dataset.baseWidth = baseWidth;

      container.style.width    = "";
      container.style.maxWidth = "";
    } else {
      frame.classList.add("horizontal-frame");
      container.style.width    = "";
      container.style.maxWidth = "";
    }

    frame.appendChild(img);
    container.appendChild(frame);

    // Force reflow so the browser paints the image before the transition
    // eslint-disable-next-line no-unused-expressions
    img.offsetHeight;

    requestAnimationFrame(() => {
      const current = container.querySelector(".photo-frame.active");
      if (current) {
        current.classList.remove("active");
        // Snap outgoing vertical frame back so it doesn't linger scaled.
        if (current.classList.contains("vertical-frame")) {
          current.style.transform = "translateX(-50%) scaleX(1)";
        }
      }

      requestAnimationFrame(() => {
        frame.classList.add("active");
        // Grow vertical frame horizontally from its centre via scaleX.
        if (frame.classList.contains("vertical-frame")) {
          frame.style.transform = "translateX(-50%) scaleX(1.1)";
        }
      });
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
  if (slideAdvanceRunning) return;
  slideAdvanceRunning = true;

  try {
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
  } finally {
    slideAdvanceRunning = false;
  }
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
 * Cycle through all upcoming photos as pages of 3×3 grids.
 *
 * Each page shows 9 photos in a 3-column × 3-row layout. Photos appear with
 * a left-to-right, top-to-bottom stagger, hold for a beat, then the whole
 * grid fades out before the next page fades in. This repeats until all photos
 * in `window.photos` have been shown (up to 36 — the next slideshow batch).
 *
 * No canvas, no rAF loop. Every transition is a CSS opacity/transform on
 * individual <div> cells, so the Pi compositor handles all compositing in
 * hardware with zero JS per frame.
 *
 * Timing per page:
 *   • Cell stagger    :  60 ms × cell index (9 cells → ~480 ms total)
 *   • Cell fade-in    : 400 ms CSS transition (opacity + scale 0.92 → 1)
 *   • Hold            : 1 600 ms after last cell is fully visible
 *   • Page fade-out   :  500 ms CSS transition on wrapper opacity
 *   • Gap between pages: 200 ms blank pause
 *
 * @async
 * @returns {Promise<void>} Resolves when all pages have been shown and
 *   the final grid has faded out.
 * @exports burstPhotos
 */
async function burstPhotos() {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;

  await preloadAllThumbs();

  // Remove any leftover overlay from an interrupted previous cycle.
  panel.querySelectorAll(".burst-grid").forEach((el) => el.remove());

  const container = $(SELECTORS.photoContainer);
  if (container) container.innerHTML = "";

  const photos = window.photos || [];
  if (!photos.length) return;

  // ── Layout constants ──────────────────────────────────────────────────────
  const COLS = 3;
  const ROWS = 3;
  const PAGE_SIZE = COLS * ROWS; // 9
  const GAP = 10; // px between cells

  // Derive the burst grid dimensions from state.panels — the same source
  // layout.js uses in getPanelDimensions() — so the grid always matches the
  // panel's *intended* size regardless of where the CSS transition is mid-flight.
  //
  // Rules (mirroring getPanelDimensions exactly):
  //   • Spotify playing OR calendarFullOpacity → panel is 69 % of viewport width.
  //     If swapped → panel starts at left: 30 %, so the grid's left inset
  //     must compensate by that 30 % so cells don't bleed into the right panel.
  //   • Otherwise → panel is 99 % of viewport width, no left compensation needed.
  const { swapped, calendarFullOpacity, spotifyPlaying } = state.panels;
  const isNarrow = spotifyPlaying || calendarFullOpacity;

  // Grid geometry — fixed rules regardless of panel CSS state:
  //
  //   Grid is always 70% of viewport wide.
  //
  //   Offset (left edge of grid, viewport-relative):
  //     swapped     → 30% (photo panel is on the right, clear the info panel)
  //     not swapped → 0   (photo panel is on the left, flush)
  const viewW    = window.innerWidth;
  const panelH   = panel.clientHeight || window.innerHeight;
  const panelW   = Math.round(viewW * 0.70);

  // Cells fill the panel with equal margins on all sides.
  const cellW = Math.floor((panelW - GAP * (COLS + 1)) / COLS);
  const cellH = Math.floor((panelH - GAP * (ROWS + 1)) / ROWS);

  // ── Inject shared cell styles once ───────────────────────────────────────
  const STYLE_ID = "burst-grid-style";
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .burst-cell {
        position: absolute;
        border-radius: 12px;
        overflow: hidden;
        opacity: 0;
        transform: scale(0.93);
        transition: opacity 400ms ease, transform 400ms ease;
        will-change: opacity, transform;
      }
      .burst-cell.visible {
        opacity: 1;
        transform: scale(1);
      }
      .burst-cell img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
    `;
    document.head.appendChild(style);
  }

  // ── Timing constants ──────────────────────────────────────────────────────
  const STAGGER_MS     = 60;   // delay between each cell appearing
  const FADE_IN_MS     = 400;  // must match CSS transition
  const HOLD_MS        = 1600; // how long the full grid stays visible
  const FADE_OUT_MS    = 500;  // wrapper opacity transition
  const BETWEEN_MS     = 200;  // blank gap between pages

  // ── Helper: show one page of up to PAGE_SIZE photos ──────────────────────
  /**
   * @param {string[]} pagePhotos - Filenames for this page (1–9 items).
   * @returns {Promise<void>} Resolves after the page has faded out.
   */
  async function showPage(pagePhotos) {
    const wrapper = document.createElement("div");
    wrapper.className = "burst-grid";
    // Explicit width/height instead of inset:0 — constrains the grid to panelW
    // even if the physical panel element is wider mid-transition. left/top are
    // always 0 because the panel's own CSS position handles the swap offset.
    // position:fixed so left/width are relative to the viewport, not the panel.
    // left transition matches the panel swap animation (1.2s cubic-bezier).
    Object.assign(wrapper.style, {
      position:      "fixed",
      // Read offset fresh — state.panels may have changed since burstPhotos() started
      // (e.g. a panel swap fired between pages).
      left:          `${(state.panels.swapped && !state.panels.spotifyPlaying && !state.panels.calendarFullOpacity) ? Math.round(window.innerWidth * 0.30) : 0}px`,
      top:           "0",
      width:         `${panelW}px`,
      height:        `${panelH}px`,
      overflow:      "hidden",
      zIndex:        "5",
      pointerEvents: "none",
      opacity:       "1",
      transition:    `opacity ${FADE_OUT_MS}ms ease, left 1.2s cubic-bezier(0.4,0,0.2,1)`,
      willChange:    "opacity, left",
    });

    const cells = [];

    pagePhotos.forEach((filename, i) => {
      const cached = state.photos.thumbsContainer?.querySelector(
        `img[data-filename="${filename}"]`,
      );
      if (!cached || !cached.complete) return;

      const row = Math.floor(i / COLS);
      const col = i % COLS;

      // Centre a partial last row horizontally.
      const countInRow = (row === Math.floor((pagePhotos.length - 1) / COLS))
        ? ((pagePhotos.length % COLS) || COLS)
        : COLS;
      const rowLeftPad = Math.round(((COLS - countInRow) * (cellW + GAP)) / 2);

      const x = GAP + col * (cellW + GAP) + rowLeftPad;
      const y = GAP + row * (cellH + GAP);

      const cell = document.createElement("div");
      cell.className = "burst-cell";
      Object.assign(cell.style, {
        left:   `${x}px`,
        top:    `${y}px`,
        width:  `${cellW}px`,
        height: `${cellH}px`,
      });

      // cloneNode(true) reuses the already-decoded pixel data — no re-fetch.
      cell.appendChild(cached.cloneNode(true));
      wrapper.appendChild(cell);
      cells.push(cell);
    });

    if (!cells.length) return;

    panel.appendChild(wrapper);

    // Stagger fade-in — CSS transitions fire, JS only sets the class.
    const lastCellDelay = (cells.length - 1) * STAGGER_MS;
    await new Promise((resolve) => {
      cells.forEach((cell, i) => {
        setTimeout(() => cell.classList.add("visible"), i * STAGGER_MS);
      });
      setTimeout(resolve, lastCellDelay + FADE_IN_MS);
    });

    // Hold while the grid is fully visible.
    await new Promise((r) => setTimeout(r, HOLD_MS));

    // Fade out the whole wrapper in one transition.
    await new Promise((resolve) => {
      wrapper.style.opacity = "0";
      setTimeout(() => {
        wrapper.remove();
        resolve();
      }, FADE_OUT_MS + 50);
    });
  }

  // ── Page through all photos ───────────────────────────────────────────────
  const total = Math.min(photos.length, 36);

  for (let offset = 0; offset < total; offset += PAGE_SIZE) {
    const pagePhotos = photos.slice(offset, offset + PAGE_SIZE);
    await showPage(pagePhotos);

    // Brief blank pause between pages (skip after the last one).
    if (offset + PAGE_SIZE < total) {
      await new Promise((r) => setTimeout(r, BETWEEN_MS));
    }
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

/**
 * Slide any live burst-grid overlays to the new position after a panel swap.
 *
 * Called by layout.js immediately after swapPanels() updates state.panels.swapped.
 * The wrapper's CSS transition on `left` (1.2s, matching the panel animation)
 * picks up the change and animates smoothly without any rAF involvement.
 */
export function updateBurstGrid() {
  const viewW    = window.innerWidth;
  const { swapped: sw, calendarFullOpacity: cal, spotifyPlaying: spot } = state.panels;
  const newLeft  = (sw && !cal && !spot) ? Math.round(viewW * 0.30) : 0;
  document.querySelectorAll(".burst-grid").forEach((el) => {
    el.style.left = `${newLeft}px`;
  });
}

export { burstPhotos, runBurstCycle };