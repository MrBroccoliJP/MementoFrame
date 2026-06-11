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
 *   drawn in waves of 36 from a shuffled cycle pool and displayed one at a
 *   time. Each photo cross-fades in over the previous one. Images are
 *   classified as "vertical" or "horizontal" so CSS can apply appropriate
 *   sizing (cover vs contain).
 *
 *   BURST — At the end of each 36-photo batch the panel performs a burst:
 *   the *next* batch of 36 is shown as a grid of thumbnails animating in,
 *   previewing what's coming next. The burst resolves, the new batch becomes
 *   active, and a fresh next batch is pre-extracted from the pool.
 *   When the pool empties the full list is re-shuffled and a new wave begins.
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
let verticalPanelResizeLockRaf = null;
let verticalPanelResizeUnlockTimer = null;

/**
 * Initialise the photo slideshow.
 *
 * Reads `window.photos` (set globally by photos.js, served at
 * /userdata/Photos/photos.js), shuffles the full list into a cycle pool,
 * extracts the first batch of 36 as the active slideshow set, and displays
 * the first photo immediately. Starts the slideshow interval and preloads
 * all thumbnails for the burst animation.
 *
 * Cycle model:
 *   - `state.photos.cyclePool`    — remaining unshown photos this wave.
 *   - `state.photos.currentBatch` — the 36 (or fewer) photos being shown now.
 *   - `state.photos.nextBatch`    — the 36 queued for the next wave (shown in burst).
 *   When cyclePool empties, the full list is re-shuffled and a new wave starts.
 *
 * Should be called once during app startup after photos.js has loaded.
 */
export function initPhotos() {
  const list = Array.isArray(window.photos) ? window.photos.slice() : [];

  // Build the initial cycle pool and extract the first batch.
  state.photos.cyclePool = shuffle(list);
  state.photos.currentBatch = extractNextBatch();
  state.photos.nextBatch = extractNextBatch();
  state.photos.index = 0;

  showPhoto(state.photos.index);
  preloadAllThumbs();

  photosTimer = setInterval(showNextSlide, INTERVALS.PHOTOS);
}

/**
 * Extract up to 36 photos from the front of `state.photos.cyclePool`.
 *
 * If the pool is empty, re-shuffles all of `window.photos` into a fresh pool
 * first (starting a new wave with no repeats until the next pool is exhausted).
 *
 * @returns {string[]} Array of up to 36 photo filenames.
 */
function extractNextBatch() {
  if (!state.photos.cyclePool || state.photos.cyclePool.length === 0) {
    const list = Array.isArray(window.photos) ? window.photos.slice() : [];
    state.photos.cyclePool = shuffle(list);
  }
  return state.photos.cyclePool.splice(0, 36);
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
 * Light panel material is only used when a horizontal photo fills the display
 * and the layout has not narrowed the photo panel for Spotify or big mode.
 */
export function updatePhotoPanelFullModeClass() {
  const activePhotoVertical = document.body.classList.contains("active-photo-vertical");
  const burstActive = document.body.classList.contains("photo-burst-active");
  const panelIsNarrow = state.panels.bigModeActive || state.panels.spotifyPlaying;
  document.body.classList.toggle("photo-panel-full-mode", !activePhotoVertical && !panelIsNarrow && !burstActive);
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
 * Also preloads the *next* photo in the current batch to reduce flash.
 *
 * @param {number} index - Index into `state.photos.currentBatch`.
 */
function showPhoto(index) {
  const container = $(SELECTORS.photoContainer);
  if (!container || !state.photos.currentBatch?.length) return;

  const name = state.photos.currentBatch[index];
  const img = new Image();
  img.src = `${PATHS.PHOTOS_FULL}${name}`;

  img.onload = () => {
    // Classify orientation for CSS sizing rules
    if (img.naturalHeight > img.naturalWidth) {
      img.classList.add("vertical");
      img.classList.remove("horizontal");
      document.body.classList.add("active-photo-vertical");
    } else {
      img.classList.add("horizontal");
      img.classList.remove("vertical");
      document.body.classList.remove("active-photo-vertical");
    }
    updatePhotoPanelFullModeClass();

    const frame = document.createElement("div");
    frame.className = "photo-frame";

    if (img.classList.contains("vertical")) {
      frame.classList.add("vertical-frame");

      // Keep the frame's centre completely stable during vertical zoom.
      // The outer frame is created at the final zoom width and only its clip
      // opens from the centre. That avoids animating layout width, which was
      // causing the left/right wobble on Chromium/RPi.
      const aspect = img.naturalWidth / img.naturalHeight;
      const baseWidth = Math.round(container.clientHeight * aspect);
      const zoomWidth = Math.round(baseWidth * 1.1);
      const clipInset = Math.round((zoomWidth - baseWidth) / 2);

      frame.style.width = `${zoomWidth}px`;
      frame.style.setProperty("--vertical-clip-inset", `${clipInset}px`);
      frame.dataset.baseWidth = `${baseWidth}`;

      const zoomInner = document.createElement("div");
      zoomInner.className = "photo-zoom-inner";
      zoomInner.style.width = `${baseWidth}px`;
      zoomInner.appendChild(img);
      frame.appendChild(zoomInner);

      container.style.width = "";
      container.style.maxWidth = "";
    } else {
      frame.classList.add("horizontal-frame");
      frame.appendChild(img);
      container.style.width = "";
      container.style.maxWidth = "";
    }

    container.appendChild(frame);

    // Force reflow so the browser paints the image before the transition
    // eslint-disable-next-line no-unused-expressions
    img.offsetHeight;

    // Force reflow so the browser records opacity:0 as the "from" state.
    // eslint-disable-next-line no-unused-expressions
    frame.offsetHeight;

    requestAnimationFrame(() => {
      const current = container.querySelector(".photo-frame.active");

      if (current) {
        current.style.transition = "opacity 450ms ease";
        current.classList.remove("active");

        setTimeout(() => {
          frame.classList.add("active");
        }, 180);
      } else {
        frame.classList.add("active");
      }
    });

    // Clean up old images after the fade transition completes
    setTimeout(() => {
      const all = $$(".photo-frame", container);
      all.slice(0, -1).forEach((n) => n.remove());
    }, 900);
  };

  // Preload the next slide in the current batch while the current one is displayed
  const next = state.photos.currentBatch[index + 1];
  if (next) {
    const preload = new Image();
    preload.src = `${PATHS.PHOTOS_FULL}${next}`;
  }
}

/**
 * Advance to the next slide, or trigger a burst at the end of each batch.
 *
 * Cycle model:
 *   - Each batch is up to 36 photos drawn from `state.photos.cyclePool`.
 *   - `state.photos.nextBatch` is pre-extracted so the burst can preview it.
 *   - When the current batch is exhausted:
 *       1. Run burstPhotos(nextBatch) — shows the *upcoming* photos.
 *       2. Promote nextBatch → currentBatch.
 *       3. Extract a fresh nextBatch from the pool (refilling if empty).
 *       4. Reset index to 0 and show the first photo of the new batch.
 *
 * Otherwise simply calls showPhoto with the incremented index.
 */
async function showNextSlide() {
  if (slideAdvanceRunning) return;
  slideAdvanceRunning = true;

  try {
    const batch = state.photos.currentBatch;
    if (!batch?.length) return;

    state.photos.index++;

    // End of current batch — run burst then roll over to next batch.
    if (state.photos.index >= batch.length) {
      await burstPhotos(state.photos.nextBatch);
      await new Promise((r) => setTimeout(r, 1000));

      // Promote the previewed batch and pre-extract the one after that.
      state.photos.currentBatch = state.photos.nextBatch;
      state.photos.nextBatch = extractNextBatch();
      state.photos.index = 0;

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
 * Cycle through the next batch of upcoming photos as pages of 3×3 grids.
 *
 * Each page shows 9 photos in a 3-column × 3-row layout. Photos appear with
 * a left-to-right, top-to-bottom stagger, hold for a beat, then the whole
 * grid fades out before the next page fades in. This repeats until all photos
 * in `photosToShow` have been shown (up to 36 — the next slideshow batch).
 *
 * `photosToShow` should be `state.photos.nextBatch` — the pre-extracted set
 * that will become the active batch after the burst completes. This means the
 * burst always previews exactly what's coming next, with no repeats from the
 * current batch.
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
 * @param {string[]} [photosToShow] - Filenames to display in the burst.
 *   Defaults to `state.photos.nextBatch` if omitted.
 * @returns {Promise<void>} Resolves when all pages have been shown and
 *   the final grid has faded out.
 * @exports burstPhotos
 */
async function burstPhotos(photosToShow) {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;

  await preloadAllThumbs();

  // Remove any leftover overlay from an interrupted previous cycle.
  panel.querySelectorAll(".burst-grid").forEach((el) => el.remove());

  const container = $(SELECTORS.photoContainer);
  if (container) container.innerHTML = "";

  const photos = (Array.isArray(photosToShow) && photosToShow.length)
    ? photosToShow
    : (state.photos.nextBatch || []);
  if (!photos.length) return;

  document.body.classList.add("photo-burst-active");
  updatePhotoPanelFullModeClass();

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
  //   • Spotify playing OR bigModeActive → panel is 69 % of viewport width.
  //     If swapped → panel starts at left: 30 %, so the grid's left inset
  //     must compensate by that 30 % so cells don't bleed into the right panel.
  //   • Otherwise → panel is 99 % of viewport width, no left compensation needed.
  const { swapped, bigModeActive, spotifyPlaying } = state.panels;
  const isNarrow = spotifyPlaying || bigModeActive;

  // Grid geometry — fixed rules regardless of panel CSS state:
  //
  //   Grid is always 70% of viewport wide.
  //
  //   Offset (left edge of grid, viewport-relative):
  //     swapped     → 30% (photo panel is on the right, clear the info panel)
  //     not swapped → 0   (photo panel is on the left, flush)
  const viewW = window.innerWidth;
  const panelH = panel.clientHeight || window.innerHeight;
  const panelW = Math.round(viewW * 0.70);

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
  const STAGGER_MS = 60;   // delay between each cell appearing
  const FADE_IN_MS = 400;  // must match CSS transition
  const HOLD_MS = 1600; // how long the full grid stays visible
  const FADE_OUT_MS = 500;  // wrapper opacity transition
  const BETWEEN_MS = 200;  // blank gap between pages

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
      position: "fixed",
      // Read offset fresh — state.panels may have changed since burstPhotos() started
      // (e.g. a panel swap fired between pages).
      left: `${(state.panels.swapped && !state.panels.spotifyPlaying && !state.panels.bigModeActive) ? Math.round(window.innerWidth * 0.30) : 0}px`,
      top: "0",
      width: `${panelW}px`,
      height: `${panelH}px`,
      overflow: "hidden",
      zIndex: "5",
      pointerEvents: "none",
      opacity: "1",
      transition: `opacity ${FADE_OUT_MS}ms ease, left 1.2s cubic-bezier(0.4,0,0.2,1)`,
      willChange: "opacity, left",
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
        left: `${x}px`,
        top: `${y}px`,
        width: `${cellW}px`,
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

  try {
    for (let offset = 0; offset < total; offset += PAGE_SIZE) {
      const pagePhotos = photos.slice(offset, offset + PAGE_SIZE);
      await showPage(pagePhotos);

      // Brief blank pause between pages (skip after the last one).
      if (offset + PAGE_SIZE < total) {
        await new Promise((r) => setTimeout(r, BETWEEN_MS));
      }
    }
  } finally {
    document.body.classList.remove("photo-burst-active");
    updatePhotoPanelFullModeClass();
  }
}

//debug function to trigger the burst manually without waiting for the slideshow cycle
async function runBurstCycle() {
  await burstPhotos(state.photos.nextBatch);
  await new Promise((r) => setTimeout(r, 1000));

  state.photos.currentBatch = state.photos.nextBatch;
  state.photos.nextBatch = extractNextBatch();
  state.photos.index = 0;

  showPhoto(state.photos.index);
}


/**
 * Hold the currently active vertical photo at the same viewport centre while
 * the left panel is being resized/repositioned for Spotify or full-calendar
 * mode.
 *
 * The vertical photo CSS deliberately maps these states to almost the same
 * final viewport centre, but during the panel width/left transition the
 * intermediate maths can drift. While the panel is animating, this function
 * writes a pixel-based left value every frame using the current container rect,
 * so the photo does not visibly move left/right. Once the panel transition is
 * over, the inline value is removed and normal CSS positioning resumes.
 *
 * @param {number} durationMs - How long to keep the stabilisation active.
 */
export function stabilizeActiveVerticalPhotoDuringPanelResize(durationMs = 700) {
  const container = $(SELECTORS.photoContainer);
  const frame = container?.querySelector(".photo-frame.vertical-frame.active");
  if (!container || !frame) return;

  const frameRect = frame.getBoundingClientRect();
  if (!frameRect.width || !frameRect.height) return;

  const targetCenterX = frameRect.left + frameRect.width / 2;
  const endAt = performance.now() + durationMs;

  if (verticalPanelResizeLockRaf) {
    cancelAnimationFrame(verticalPanelResizeLockRaf);
    verticalPanelResizeLockRaf = null;
  }
  if (verticalPanelResizeUnlockTimer) {
    clearTimeout(verticalPanelResizeUnlockTimer);
    verticalPanelResizeUnlockTimer = null;
  }

  frame.classList.add("vertical-panel-resize-lock");

  const keepCentered = () => {
    if (!frame.isConnected || !frame.classList.contains("active")) {
      verticalPanelResizeLockRaf = null;
      return;
    }

    const containerRect = container.getBoundingClientRect();
    frame.style.setProperty(
      "--vertical-photo-left",
      `${targetCenterX - containerRect.left}px`,
    );

    if (performance.now() < endAt) {
      verticalPanelResizeLockRaf = requestAnimationFrame(keepCentered);
    } else {
      verticalPanelResizeLockRaf = null;
      verticalPanelResizeUnlockTimer = setTimeout(() => {
        frame.classList.remove("vertical-panel-resize-lock");
        frame.style.removeProperty("--vertical-photo-left");
        verticalPanelResizeUnlockTimer = null;
      }, 50);
    }
  };

  keepCentered();
}

/**
 * Slide any live burst-grid overlays to the new position after a panel swap.
 *
 * Called by layout.js immediately after swapPanels() updates state.panels.swapped.
 * The wrapper's CSS transition on `left` (1.2s, matching the panel animation)
 * picks up the change and animates smoothly without any rAF involvement.
 */
export function updateBurstGrid() {
  const viewW = window.innerWidth;
  const { swapped: sw, bigModeActive: bma, spotifyPlaying: spot } = state.panels;
  const newLeft = (sw && !bma && !spot) ? Math.round(viewW * 0.30) : 0;
  document.querySelectorAll(".burst-grid").forEach((el) => {
    el.style.left = `${newLeft}px`;
  });
}

export { burstPhotos, runBurstCycle };
