import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, $$ } from "../utils.js";

export function initPhotos() {
  // window.photos is defined by /userdata/Photos/photos.js
  const list = Array.isArray(window.photos) ? window.photos.slice() : [];
  state.photos.shuffled = shuffle(list);
  state.photos.index = 0;

  // initial
  showPhoto(state.photos.index);
  preloadAllThumbs();

  setInterval(showNextSlide, INTERVALS.PHOTOS);
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random()*(i+1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function showPhoto(index) {
  const container = $(SELECTORS.photoContainer);
  if (!container || !state.photos.shuffled.length) return;

  const name = state.photos.shuffled[index];
  const img = new Image();
  img.src = `${PATHS.PHOTOS_FULL}${name}`;

  img.onload = () => {
    if (img.naturalHeight > img.naturalWidth) {
      img.classList.add("vertical"); img.classList.remove("horizontal");
    } else {
      img.classList.add("horizontal"); img.classList.remove("vertical");
    }

    container.appendChild(img);
    // force reflow
    // eslint-disable-next-line no-unused-expressions
    img.offsetHeight;

    requestAnimationFrame(() => {
      const current = container.querySelector("img.active");
      if (current) current.classList.remove("active");
      requestAnimationFrame(() => img.classList.add("active"));
    });

    // clean old after transition
    setTimeout(() => {
      const all = $$(".photo img", container);
      all.slice(0, -1).forEach(n => n.remove());
    }, 2100);
  };

  // preload next
  const next = state.photos.shuffled[index + 1];
  if (next) {
    const preload = new Image();
    preload.src = `${PATHS.PHOTOS_FULL}${next}`;
  }
}

function showNextSlide() {
  if (!state.photos.shuffled.length) return;
  state.photos.index = (state.photos.index + 1) % state.photos.shuffled.length;

  if (state.photos.index % 36 === 0) {
    const container = $(SELECTORS.photoContainer);
    if (container) container.innerHTML = "";
    burstPhotos();
    state.photos.index = 0;
    state.photos.shuffled = shuffle([...state.photos.shuffled]);
    return;
    }
  showPhoto(state.photos.index);
}

function preloadAllThumbs() {
  if (state.photos.thumbsContainer) return;
  const div = document.createElement("div");
  div.style.display = "none";
  (document.body || document.documentElement).appendChild(div);
  state.photos.thumbsContainer = div;

  (window.photos || []).forEach(filename => {
    const img = new Image();
    img.src = `${PATHS.PHOTOS_THUMBS}${filename}`;
    img.dataset.filename = filename;
    div.appendChild(img);
  });
}

function burstPhotos() {
  const panel = $(SELECTORS.leftPanel);
  if (!panel) return;
  panel.querySelectorAll(".floating-photo").forEach(el => el.remove());

  preloadAllThumbs();

  const photosPerRow = 7;
  const panelWidth = panel.clientWidth;
  const thumbWidth = Math.min(100, panelWidth / photosPerRow);
  const gap = 10;

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

    img.style.width = `${thumbWidth - gap}px`;
    img.style.left = `${col * thumbWidth + horizontalOffset}px`;
    img.style.bottom = `${row * (120 + gap)}px`;
    panel.appendChild(img);
    img.addEventListener("animationend", () => img.remove());
  });
}

export { burstPhotos };
