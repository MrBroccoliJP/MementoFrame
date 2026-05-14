export function hideLoadingScreen() {
  const el = document.getElementById("loading-screen");
  if (!el) return;

  el.classList.add("hidden");
  setTimeout(() => el.remove(), 700);
}

export function setLoadingStatus(text) {
  const el = document.getElementById("statusText");
  if (el) el.textContent = text;
}

export async function loadVersions() {
  try {
    const res = await fetch("/versions");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const el = document.getElementById("versions");
    if (!el) return;

    const version = data.tag || (data.version ? `v${data.version}` : null);

    el.innerHTML = version
      ? `<span>MementoFrame ${version}</span>`
      : "";
  } catch (e) {
    console.warn("versions failed", e);
  }
}

export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));