import assert from "node:assert/strict";

import {
  isUpdateStateActive,
  shouldAcceptUpdateState,
} from "../static/js/modules/updater.js";


const active = {
  state_revision: 10,
  state_valid: true,
  update_in_progress: true,
  update_phase: "applying",
};

assert.equal(
  shouldAcceptUpdateState(active, {
    state_revision: 9,
    state_valid: true,
    update_in_progress: false,
    update_phase: "idle",
  }),
  false,
  "a delayed pre-update poll must not hide a newer active state",
);

assert.equal(
  shouldAcceptUpdateState(active, {
    state_revision: 11,
    state_valid: false,
    update_in_progress: false,
    update_phase: "idle",
  }),
  false,
  "an invalid state-file read must not clear an active overlay",
);

assert.equal(
  shouldAcceptUpdateState(active, {
    state_revision: 11,
    state_valid: true,
    update_in_progress: false,
    update_phase: "complete",
  }),
  true,
  "a newer explicit completion must be accepted",
);

assert.equal(
  isUpdateStateActive({ post_reboot_pending: true, update_phase: "verifying" }),
  true,
  "post-reboot verification must keep the overlay active",
);

assert.equal(
  isUpdateStateActive({ download_in_progress: true, update_phase: "downloading" }),
  false,
  "downloading an update must not activate the overlay",
);

assert.equal(
  isUpdateStateActive({ download_in_progress: true, update_phase: "preparing" }),
  false,
  "preparing a downloaded archive must not activate the overlay",
);

assert.equal(
  isUpdateStateActive({ rollback_post_reboot_attempt: 1, update_phase: "complete" }),
  false,
  "historical rollback attempt metadata must not keep the overlay stuck",
);

console.log("updater frontend lifecycle tests passed");
