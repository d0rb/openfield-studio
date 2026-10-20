// A tiny observable store: enough state management for a no-build app.

export function createStore(initial = {}) {
  let state = { ...initial };
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === "function" ? patch(state) : patch;
      const changed = Object.keys(next).filter((k) => !Object.is(state[k], next[k]));
      if (!changed.length) return;
      state = { ...state, ...next };
      for (const listener of [...listeners]) listener(state, changed);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
