// Application controller: loads data, starts takes, follows them live and keeps the store current.
// No DOM in here, so it can be tested with a fake api.

import { TERMINAL } from "./lib/status.js";
import { emptyLive, reduceLive } from "./lib/live.js";

const STATUS_POLL_MS = 15000;

export function createController({ api, store, setInterval: every = globalThis.setInterval, now = Date.now }) {
  const stops = new Map();
  let statusTimer = null;

  const fail = (error) => {
    const entry = { id: now(), code: error.code ?? "error", message: error.message ?? String(error) };
    store.set((s) => ({ notices: [...s.notices, entry].slice(-4) }));
    return entry;
  };
  const dismiss = (id) => store.set((s) => ({ notices: s.notices.filter((n) => n.id !== id) }));

  const upsertTake = (take) =>
    store.set((s) => {
      const rest = s.takes.filter((t) => t.id !== take.id);
      return { takes: [take, ...rest].sort((a, b) => b.created_at.localeCompare(a.created_at)) };
    });

  const setLive = (takeId, event) =>
    store.set((s) => ({ live: { ...s.live, [takeId]: reduceLive(s.live[takeId] ?? emptyLive(), event) } }));

  function track(take) {
    upsertTake(take);
    if (TERMINAL.has(take.status) || stops.has(take.id)) return;
    stops.set(
      take.id,
      api.follow(take.id, {
        onEvent: (event) => {
          setLive(take.id, event);
          if (event.type === "take") upsertTake(event.take);
        },
        onEnd: () => {
          stops.delete(take.id);
          api.take(take.id).then(upsertTake).catch(fail);
        },
      }),
    );
  }

  async function guard(work) {
    try {
      return await work();
    } catch (error) {
      fail(error);
      return null;
    }
  }

  return {
    store,
    dismiss,

    async load() {
      const [status, moves, takes, cast, recorded] = await Promise.all([
        guard(() => api.status()),
        guard(() => api.moves()),
        guard(() => api.takes({ limit: 200 })),
        guard(() => api.cast.list()),
        guard(() => api.recorded()),
      ]);
      store.set({ status, moves, takes: takes ?? [], cast: cast ?? [], recorded: recorded ?? [], loaded: true });
      // the moving tiles: never in the way of the first paint; false (not null) once the answer is "none", so nothing waits on
      api.previews?.().then((previews) => store.set({ previews: previews || false })).catch(() => store.set({ previews: false }));
      for (const take of takes ?? []) if (!TERMINAL.has(take.status)) track(take);
      statusTimer ??= every(() => { this.refreshStatus(); this.refreshTakes(); }, STATUS_POLL_MS);
    },

    /** Re-read the ledger: a take started in another tab or by a script appears, and is followed if it is still running. */
    async refreshTakes() {
      const takes = await guard(() => api.takes({ limit: 200 }));
      if (!takes) return;
      store.set((s) => ({ takes: [...takes].sort((a, b) => b.created_at.localeCompare(a.created_at)), selected: s.selected }));
      for (const take of takes) if (!TERMINAL.has(take.status)) track(take);
    },

    async refreshStatus() {
      const status = await guard(() => api.status());
      if (status) store.set({ status });
    },

    async setBackend(mode) {
      const status = await guard(() => api.setBackend(mode));
      if (status) store.set({ status });
      return status;
    },

    /** Probe a target without switching; the result card is the caller's to draw. */
    async testBackend(body) {
      return guard(() => api.testBackend(body));
    },

    async connectBackend(body) {
      const status = await guard(() => api.connectBackend(body));
      if (status) store.set({ status });
      return status;
    },

    async forgetBackend() {
      const status = await guard(() => api.forgetBackend());
      if (status) store.set({ status });
      return status;
    },

    async startDirect(body) {
      const take = await guard(() => api.startDirect(body));
      if (take) {
        track(take);
        store.set({ selected: take.id });
      }
      return take;
    },

    async startDirectFromImage(form) {
      const take = await guard(() => api.startDirectFromImage(form));
      if (take) {
        track(take);
        store.set({ selected: take.id });
      }
      return take;
    },

    /** Replay a recorded take as a new take (Replay mode: the first-minute path). */
    async recreate(recordedId) {
      const take = await guard(() => api.recreate(recordedId));
      if (take) {
        track(take);
        store.set({ selected: take.id });
      }
      return take;
    },

    async startShots(form) {
      const take = await guard(() => api.startShots(form));
      if (take) track(take);
      return take;
    },

    async startTransition(body) {
      const take = await guard(() => api.startTransition(body));
      if (take) track(take);
      return take;
    },

    /** Continue a finished take from its last frame; the sheet opens the new take. */
    async startExtend(takeId, seconds) {
      const take = await guard(() => api.startExtend({ take: takeId, seconds }));
      if (take) track(take);
      return take;
    },

    /** Enlarge a finished take to 2K or 4K; the sheet opens the new take. */
    async startUpscale(takeId, target) {
      const take = await guard(() => api.startUpscale({ take: takeId, target }));
      if (take) track(take);
      return take;
    },

    async startEdit(form) {
      const take = await guard(() => api.startEdit(form));
      if (take) track(take);
      return take;
    },

    async startReshoot(form) {
      const take = await guard(() => api.startReshoot(form));
      if (take) {
        track(take);
        store.set({ selected: take.id });
      }
      return take;
    },

    async approve(takeId, reroll = []) {
      return guard(() => api.approve(takeId, reroll));
    },

    async cancel(takeId) {
      const take = await guard(() => api.cancel(takeId));
      if (take) upsertTake(take);
      return take;
    },

    async remove(takeId) {
      stops.get(takeId)?.();
      stops.delete(takeId);
      const done = await guard(async () => {
        await api.remove(takeId);
        return true;
      });
      if (done) store.set((s) => ({ takes: s.takes.filter((t) => t.id !== takeId), selected: s.selected === takeId ? null : s.selected }));
    },

    async refreshCast() {
      const cast = await guard(() => api.cast.list());
      if (cast) store.set({ cast });
    },

    async createCast(form) {
      const cast = await guard(() => api.cast.create(form));
      if (cast) await this.refreshCast();
      return cast;
    },

    /** Generate candidate portraits of an invented character; follow the take to see them arrive. */
    async generateCharacter(body) {
      const take = await guard(() => api.cast.generate(body));
      if (take) track(take);
      return take;
    },

    /** Keep one finished candidate as a Cast. */
    async keepCandidate(takeId, candidate, name) {
      const cast = await guard(() => api.cast.fromTake(takeId, candidate, name));
      if (cast) await this.refreshCast();
      return cast;
    },

    async removeCast(id) {
      await guard(() => api.cast.remove(id));
      await this.refreshCast();
    },

    async exportVertical(takeId, focusX) {
      const take = await guard(() => api.exportVertical(takeId, focusX));
      if (take) upsertTake(take);
      return take;
    },

    async exportReel(takeIds, crossfade) {
      const take = await guard(() => api.exportReel(takeIds, crossfade));
      if (take) upsertTake(take);
      return take;
    },

    select(takeId) {
      store.set({ selected: takeId });
    },

    stop() {
      for (const stop of stops.values()) stop();
      stops.clear();
      if (statusTimer) clearInterval(statusTimer);
      statusTimer = null;
    },
  };
}

export const initialState = () => ({
  loaded: false,
  status: null,
  moves: null,
  takes: [],
  cast: [],
  recorded: [],
  previews: null,
  selected: null,
  live: {},
  notices: [],
  route: "lobby",
});
