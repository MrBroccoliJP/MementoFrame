export const PATHS = {
  CONFIG: "/config.json",
  WEATHER: "/weather.json",
  SPOTIFY: "/spotify.json",
  STATUS: "/status.json",
  SCREEN_ON: "/screen/on",
  SCREEN_OFF: "/screen/off",
  CONFIG_STREAM: "/config/stream",

  PHOTOS_FULL: "/userdata/Photos/full/",
  PHOTOS_THUMBS: "/userdata/Photos/thumbs/",

  WEATHER_OFFLINE_ICON: "/assets/Icons/weather_offline.svg",
};

export const INTERVALS = {
  CLOCK: 1000,
  SPOTIFY: 5000,
  WIFI: 30000,
  WEATHER: 30 * 60 * 1000, // 30m
  PHOTOS: 20000,
  QR: 30000,
  HOURLY_CHECK: 60000,
  SWAP_PANELS: 60 * 60 * 1000, // 1h
  CALENDAR_FULL_TIMEOUT: 5 * 60 * 1000, // 5m
};

export const SELECTORS = {
  clock1: "#clock",
  clock2: "#clock2",
  day: "#day-number",
  monthYear: "#month-year",
  dualBox: ".dual_clock-box",
  clock1Box: ".clock-box-left",
  clock2Box: ".clock-box-right",
  dateBox: ".date-box",
  firstRow: ".first-row",
  secondRow: ".second_row",
  calendarBox: "#calendar-box",
  calendarEl: "#calendar",
  spotifyBox: "#spotify-box",
  albumCover: "#album-cover",
  trackName: "#track-name",
  trackArtist: "#track-artist",
  trackStatus: "#track-status",
  liked: "#track-liked",
  progressBar: "#progress-bar",
  weatherBox: ".weather-box",
  weatherTemp: ".weather-temperature",
  weatherCond: ".weather-condition",
  weatherIcon: "#weather-icon",
  leftPanel: ".left_panel",
  rightPanel: ".right_panel",
  wifiStatus: "#wifi-status",
  qrContainer: ".qrcode_icon",
  photoContainer: ".photo",
  systemInfoBox: ".system-info-box",
};
