// Take states shared by the API clients, the live-event follower and the controller.

/** A take in one of these states will never change again. */
export const TERMINAL = new Set(["succeeded", "failed", "canceled"]);
