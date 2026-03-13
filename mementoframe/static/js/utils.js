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

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

export function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

export function onceImgLoaded(img, cb) {
  if (!img) return;
  if (img.complete && img.naturalWidth > 0) cb();
  else img.onload = cb;
}

export function debounce(fn, ms = 200) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
