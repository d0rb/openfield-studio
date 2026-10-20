// Live take events over Server-Sent Events, with a polling fallback.
//
// The server replays a take's whole history on every connection, so reconnecting is safe and
// handlers must be idempotent (the UI derives its state from the latest `take` event).

import { TERMINAL } from "./status.js";

/**
 * Follow a take. Calls onEvent(event) for every event and onEnd(status) once.
 * Returns a function that stops following.
 */
export function followTake(api, takeId, { onEvent, onEnd, pollMs = 2000, EventSourceImpl = globalThis.EventSource } = {}) {
  let closed = false;
  let source = null;
  let timer = null;

  const finish = (status) => {
    if (closed) return;
    stop();
    onEnd?.(status);
  };

  const poll = async () => {
    if (closed) return;
    try {
      const take = await api.take(takeId);
      onEvent?.({ type: "take", take, polled: true });
      if (TERMINAL.has(take.status)) return finish(take.status);
    } catch (error) {
      onEvent?.({ type: "error", error: { code: error.code ?? "network", message: error.message } });
    }
    timer = setTimeout(poll, pollMs);
  };

  const stop = () => {
    closed = true;
    source?.close();
    clearTimeout(timer);
  };

  if (!EventSourceImpl) {
    poll();
    return stop;
  }
  source = new EventSourceImpl(api.eventsUrl(takeId));
  source.onmessage = (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    onEvent?.(event);
    if (event.type === "end") finish(event.status);
  };
  source.onerror = () => {
    // The browser would retry on its own, but a finished take closes the stream for good:
    // check the real state once, then either finish or let EventSource reconnect.
    if (closed) return;
    api
      .take(takeId)
      .then((take) => {
        if (TERMINAL.has(take.status)) {
          onEvent?.({ type: "take", take });
          finish(take.status);
        }
      })
      .catch(() => {});
  };
  return stop;
}
