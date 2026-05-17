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
 * Draw a rounded rectangle path.
 *
 * @param {CanvasRenderingContext2D} ctx - Canvas rendering context.
 * @param {number} x - Rectangle x position.
 * @param {number} y - Rectangle y position.
 * @param {number} width - Rectangle width.
 * @param {number} height - Rectangle height.
 * @param {number} radius - Corner radius.
 */
function roundedRectPath(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);

  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

/**
 * Draw a burst thumbnail without distorting the source image.
 *
 * Horizontal images use object-fit: cover semantics, matching the previous
 * thumbnail look. Vertical images keep their full height and natural portrait
 * shape, centered inside the row cell instead of being cropped or stretched.
 * A rounded clipping path is applied to the actual image rectangle so canvas
 * thumbnails match the rest of the app.
 *
 * @param {CanvasRenderingContext2D} ctx - Canvas rendering context.
 * @param {HTMLImageElement} img - Image to draw.
 * @param {number} x - Target cell x position.
 * @param {number} y - Target cell y position.
 * @param {number} width - Target cell width.
 * @param {number} height - Target cell height.
 * @param {number} radius - Corner radius.
 */
function drawBurstImage(ctx, img, x, y, width, height, radius = 10) {
  const sourceWidth = img.naturalWidth || img.width;
  const sourceHeight = img.naturalHeight || img.height;

  if (!sourceWidth || !sourceHeight || !width || !height) return;

  const isVertical = sourceHeight > sourceWidth;

  let sx = 0;
  let sy = 0;
  let sw = sourceWidth;
  let sh = sourceHeight;
  let dx = x;
  let dy = y;
  let dw = width;
  let dh = height;

  if (isVertical) {
    // Portrait photos keep their full vertical image and natural aspect.
    // They become narrower, centered thumbnails instead of cropped 4:3 boxes.
    dh = height;
    dw = Math.min(width, Math.round(height * (sourceWidth / sourceHeight)));
    dx = x + Math.round((width - dw) / 2);
  } else {
    // Landscape/square photos fill the thumbnail cell using cover semantics.
    const sourceRatio = sourceWidth / sourceHeight;
    const targetRatio = width / height;

    if (sourceRatio > targetRatio) {
      sw = sourceHeight * targetRatio;
      sx = (sourceWidth - sw) / 2;
    } else {
      sh = sourceWidth / targetRatio;
      sy = (sourceHeight - sh) / 2;
    }
  }

  ctx.save();
  roundedRectPath(ctx, dx, dy, dw, dh, radius);
  ctx.clip();
  ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
  ctx.restore();
}

/**
 * Animate all thumbnail photos flying upward from the bottom of the left panel.
 *
 * Uses a single canvas instead of many independently animated DOM images. This
 * avoids compositor pressure and keeps every thumbnail update locked to the
 * same requestAnimationFrame tick, which is smoother on Raspberry Pi hardware.
 *
 * Horizontal thumbnails are drawn with object-fit: cover semantics. Vertical
 * thumbnails keep their full portrait height and are centered inside each cell.
 * The layout uses three photos per row for a lighter, calmer burst animation.
 *
 * @async
 * @returns {Promise<void>} Resolves when the burst has fully left the screen.
 * @exports burstPhotos
 */
async function burstPhotos() {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;

  await preloadAllThumbs();

  panel.querySelectorAll(".burst-canvas").forEach((el) => el.remove());

  const container = $(SELECTORS.photoContainer);
  if (container) container.innerHTML = "";

  const photos = window.photos || [];
  if (!photos.length) return;

  const photosPerRow = 3;
  const gap = 8;
  const NARROW_WIDTH = Math.floor(window.innerWidth * 0.69);
  const panelWidth = Math.min(panel.clientWidth, NARROW_WIDTH);
  const panelHeight = panel.clientHeight;

  const thumbWidth = Math.floor(panelWidth / photosPerRow);
  const thumbHeight = Math.round(thumbWidth * 0.75);
  const rowSpacing = thumbHeight + gap;
  const totalRows = Math.ceil(photos.length / photosPerRow);

  const canvas = document.createElement("canvas");
  canvas.className = "burst-canvas";
  canvas.width = panelWidth;
  canvas.height = panelHeight;

  canvas.style.position = "absolute";
  canvas.style.left = "var(--burst-x-offset, 0px)";
  canvas.style.top = "0";
  canvas.style.width = `${panelWidth}px`;
  canvas.style.height = `${panelHeight}px`;
  canvas.style.pointerEvents = "none";
  canvas.style.zIndex = "5";

  panel.appendChild(canvas);

  const ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx) {
    canvas.remove();
    return;
  }

  const items = photos
    .map((filename, idx) => {
      const cached = state.photos.thumbsContainer?.querySelector(
        `img[data-filename="${filename}"]`,
      );
      if (!cached || !cached.complete) return null;

      const row = Math.floor(idx / photosPerRow);
      const col = idx % photosPerRow;

      const isLastRow = row === totalRows - 1;
      const countInRow = isLastRow
        ? photos.length % photosPerRow || photosPerRow
        : photosPerRow;
      const rowOffset = isLastRow
        ? Math.floor((photosPerRow - countInRow) / 2) * thumbWidth
        : 0;

      return {
        img: cached,
        x: col * thumbWidth + rowOffset,
        y: panelHeight + thumbHeight + row * rowSpacing,
        width: thumbWidth - gap,
        height: thumbHeight,
      };
    })
    .filter(Boolean);

  if (!items.length) {
    canvas.remove();
    return;
  }

  const speedPxMs = 0.32;
  const maxStartY = Math.max(...items.map((item) => item.y));
  const totalDistance = maxStartY + thumbHeight + 40;
  const duration = totalDistance / speedPxMs;
  const startTime = performance.now();

  await new Promise((resolve) => {
    function frame(now) {
      const elapsed = now - startTime;
      const offset = elapsed * speedPxMs;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (const item of items) {
        const y = item.y - offset;

        if (y < -item.height || y > panelHeight + item.height) continue;

        drawBurstImage(
          ctx,
          item.img,
          item.x,
          y,
          item.width,
          item.height,
          10,
        );
      }

      if (elapsed < duration) {
        requestAnimationFrame(frame);
      } else {
        canvas.remove();
        resolve();
      }
    }

    requestAnimationFrame(frame);
  });
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
