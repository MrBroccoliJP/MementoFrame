export const state = {
  online: false,
  config: {},
  clocks: {
    enableSecond: false,
    clock1Tz: "UTC",
    clock2Tz: "UTC",
    clock1Label: "Clock 1",
    clock2Label: "Clock 2",
    lastCalendarDate: null,
  },
  panels: {
    swapped: false,
    calendarFullOpacity: false,
    spotifyPlaying: false,
  },
  spotify: {
    lastTrackId: null,
    hideTimeout: null,
    accentTimer: null,
    currentAccent: "rgb(50, 50, 50)",
    wasPaused: false,
    pollTimer: null,
  },
  photos: {
    shuffled: [],
    index: 0,
    thumbsContainer: null,
  },
  timers: {
    calendarFullTimeout: null,
  },
};
