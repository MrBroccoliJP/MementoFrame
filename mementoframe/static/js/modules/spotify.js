import { state } from "../state.js";
import { PATHS, INTERVALS, SELECTORS } from "../constants.js";
import { $, $$, fetchJson, onceImgLoaded } from "../utils.js";
import { showCalendar, setCalendarOpacity, updatePanelState } from "./layout.js";

// inline SVGs
const playSVG  = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M3 22v-20l18 10-18 10z"/></svg>`;
const pauseSVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24"><path d="M6 2h4v20h-4zm8 0h4v20h-4z"/></svg>`;

export function initSpotify() {
  startAccentColorCycle(); // initial ambient
  startSpotifyPolling(INTERVALS.SPOTIFY);
}

function startSpotifyPolling(ms) {
  if (state.spotify.pollTimer) clearInterval(state.spotify.pollTimer);
  state.spotify.pollTimer = setInterval(updateSpotify, ms);
  updateSpotify();
}

function setAccentVar(color) {
  document.documentElement.style.setProperty("--accent-color", color);
  document.documentElement.style.setProperty("--accent-text", color);
  state.spotify.currentAccent = color;
}

function ensureReadable(rgb) {
  const m = rgb.match(/\d+/g); if (!m) return rgb;
  let [r,g,b] = m.map(Number);
  const brightness = (r*299 + g*587 + b*114) / 1000;
  if (brightness < 90) {
    r = Math.min(255, r+100); g = Math.min(255, g+100); b = Math.min(255, b+100);
    return `rgb(${r}, ${g}, ${b})`;
  }
  return rgb;
}

function applyAccent(color, transition = true) {
  color = ensureReadable(color);
  setAccentVar(color);

  const spotify = $(SELECTORS.spotifyBox);
  const calendarBox = $(SELECTORS.calendarBox);
  const dualBox = $(SELECTORS.dualBox);
  const clock1Box = $(SELECTORS.clock1Box);
  const weatherBox = $(SELECTORS.weatherBox);
  const dateBox = $(SELECTORS.dateBox);

  const ts = transition ? "background 2s ease, border-color 1s ease" : "none";

  if (spotify) {
    spotify.style.transition = ts;
    spotify.style.background = `linear-gradient(135deg, ${color} 0%, #1c1c1c 100%)`;
  }
  if (calendarBox) {
    calendarBox.style.transition = ts;
    calendarBox.style.borderLeft = `3px solid ${color}`;
    // color headers and cells
    $$("#calendar th").forEach(th => th.style.color = color);
    $$("#calendar td").forEach(td => {
      td.style.color = td.classList.contains("today") ? "#111" : color;
    });
  }
  if (dualBox)   { dualBox.style.transition = ts; dualBox.style.borderBottom = `2px solid ${color}`; }
  if (clock1Box) { clock1Box.style.transition = ts; clock1Box.style.borderRight = `1px solid ${color}`; }
  if (weatherBox){ weatherBox.style.transition = ts; weatherBox.style.borderTop = `2px solid ${color}`; }
  if (dateBox)   { dateBox.style.transition = ts; dateBox.style.borderTop = `2px solid ${color}`; }
}

function randomPastel() {
  const hue = Math.floor(Math.random() * 360);
  const sat = 70 + Math.random() * 10;
  const light = 80 + Math.random() * 10;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

function startAccentColorCycle() {
  if (state.spotify.accentTimer) return;
  applyAccent(randomPastel(), false);
  state.spotify.accentTimer = setInterval(() => applyAccent(randomPastel(), true), 60 * 60 * 1000);
}
function stopAccentColorCycle() {
  if (state.spotify.accentTimer) {
    clearInterval(state.spotify.accentTimer);
    state.spotify.accentTimer = null;
  }
}

export async function updateSpotify() {
  if (!state.online) return;

  const data = await fetchJson(PATHS.SPOTIFY);
  if (!data) {
    startAccentColorCycle(); showCalendar();
    return;
  }

  const isPlaying = !!data.isPlaying;
  const trackId   = data.trackId || data.track || null;
  const name      = data.track || data.title || "";
  const artist    = data.artist || data.artists || "";
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

  const wasPlaying = state.panels.spotifyPlaying;
  const resumed = !wasPlaying && isPlaying && trackId === state.spotify.lastTrackId;

  if (!isPlaying) {
    if (!state.spotify.wasPaused) {
      state.spotify.wasPaused = true;
      if (!state.spotify.hideTimeout) {
        state.spotify.hideTimeout = setTimeout(() => {
          state.spotify.hideTimeout = null;
          stopAccentColorCycle();
          applyAccent(randomPastel(), true);
          startAccentColorCycle();
          showCalendar();
        }, 30000);
      }
    }
  } else {
    state.spotify.wasPaused = false;
    if (state.spotify.hideTimeout) { clearTimeout(state.spotify.hideTimeout); state.spotify.hideTimeout = null; }
    stopAccentColorCycle();
    // show handled in layout.showSpotify()
  }

  // resume accent refresh
  if (resumed) {
    onceImgLoaded(albumEl, () => applyAccentFromImage(albumEl, true));
  }

  // transition on track change
  if (state.spotify.lastTrackId && trackId && state.spotify.lastTrackId !== trackId) {
    albumEl?.classList.add("fade-out");
    $(SELECTORS.spotifyBox)?.querySelector(".track-info")?.classList.add("fade-out");
    setTimeout(() => {
      if (albumArt) albumEl.src = albumArt;
      if (nameEl) nameEl.textContent = name || "No track";
      if (artistEl) artistEl.textContent = artist || "Unknown";
      albumEl.onload = () => {
        albumEl.classList.remove("fade-out"); albumEl.classList.add("fade-in");
        const ti = $(SELECTORS.spotifyBox)?.querySelector(".track-info");
        ti?.classList.remove("fade-out"); ti?.classList.add("fade-in");
        setTimeout(() => { albumEl.classList.remove("fade-in"); ti?.classList.remove("fade-in"); }, 600);
        applyAccentFromImage(albumEl, true);
      };
    }, 300);
  }

  if (!state.spotify.lastTrackId && trackId) {
    if (albumArt) {
      albumEl.crossOrigin = "anonymous";
      albumEl.src = albumArt;
      albumEl.onload = () => {
        if (isPlaying) applyAccentFromImage(albumEl, true);
        else applyAccent(randomPastel(), true);
      };
    }
    if (nameEl) nameEl.textContent = name || "No track";
    if (artistEl) artistEl.textContent = artist || "Unknown";
  }

  state.spotify.lastTrackId = trackId;

  if (nameEl) nameEl.textContent = name || "No track";
  if (artistEl) artistEl.textContent = artist || "Unknown";
  if (likedEl) likedEl.style.display = liked ? "block" : "none";
  if (barEl && duration && progress !== undefined) {
    barEl.style.width = `${(progress / duration) * 100}%`;
  }

  // toggle layout views
  if (isPlaying) {
    setCalendarOpacity(1);
    updatePanelState({ calendarFullOpacity: false, spotifyPlaying: true });
    const spotifyBox = $(SELECTORS.spotifyBox);
    const calendarBox = $(SELECTORS.calendarBox);
    calendarBox?.classList.add("hidden"); calendarBox?.classList.remove("visible");
    spotifyBox?.classList.remove("hidden"); spotifyBox?.classList.add("visible");
  }
}

function applyAccentFromImage(img, transition) {
  try {
    const c = document.createElement("canvas"); const ctx = c.getContext("2d");
    c.width = img.naturalWidth || img.width; c.height = img.naturalHeight || img.height;
    ctx.drawImage(img, 0, 0, c.width, c.height);
    const data = ctx.getImageData(0,0,c.width,c.height).data;
    const counts = {};
    for (let i=0;i<data.length;i+=40) {
      const r=data[i], g=data[i+1], b=data[i+2];
      const br=(r+g+b)/3;
      if (br < 30 || br > 220) continue;
      const key = `${Math.floor(r/10)},${Math.floor(g/10)},${Math.floor(b/10)}`;
      counts[key]=(counts[key]||0)+1;
    }
    let max=0, winner="50,50,50";
    for (const k in counts) if (counts[k]>max) { max=counts[k]; winner=k; }
    const [r,g,b]=winner.split(",").map(v=>v*10);
    applyAccent(`rgb(${r}, ${g}, ${b})`, transition);
  } catch {
    applyAccent(state.spotify.currentAccent || "rgb(50, 50, 50)", transition);
  }
}
