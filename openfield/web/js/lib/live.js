// Turn a take's event stream into the small state the screens need.
// Pure functions: the same events always give the same state, and duplicates are harmless
// (the server replays a take's history on every connection).

// state of the ComfyUI run currently in flight; reset whenever a stage starts
const freshRun = () => ({ runStatus: null, queue: null, step: null, steps: null, runValue: null, preview: null, uploading: null });

export function emptyLive() {
  return {
    take: null,
    stage: null,
    stageState: null,
    index: 0,
    total: 0,
    ...freshRun(),
    identity: {},
    approval: null,
    anchorsShown: null,
    error: null,
    ended: null,
  };
}

export function reduceLive(live, event) {
  switch (event.type) {
    case "take": {
      const take = event.take;
      const approval =
        take.status === "awaiting_approval"
          ? (live.approval ?? { anchors: take.anchors ?? [] })
          : null;
      return { ...live, take, approval, identity: { ...live.identity, ...(take.identity ?? {}) } };
    }
    case "stage": {
      const next = { ...live, stage: event.stage, stageState: event.state, index: event.index, total: event.total };
      // a stage starting is a new ComfyUI run: nothing from the previous one may linger on screen
      return event.state === "start" ? { ...next, ...freshRun() } : next;
    }
    case "run":
      return reduceRun(live, event);
    case "identity":
      return { ...live, identity: { ...live.identity, [event.stage]: event.report } };
    case "approval":
      // a replayed approval already happened: show its stills, never wait on it
      return event.replayed ? { ...live, anchorsShown: event.anchors } : { ...live, approval: { anchors: event.anchors } };
    case "error":
      return { ...live, error: event.error };
    case "end":
      return { ...live, ended: event.status, approval: null };
    default:
      return live;
  }
}

function reduceRun(live, { event: e, run }) {
  switch (e.kind) {
    case "uploading":
      return { ...live, uploading: { files: e.files, bytes: e.bytes } };
    case "submitted":
      return { ...live, uploading: null, runStatus: "queued" };
    // `uploading` ends the moment the job is accepted; clear it here too so a lost `submitted` cannot pin the Monitor
    case "status":
      return { ...live, uploading: null, runStatus: e.status, queue: e.queue_position ?? null };
    case "progress":
      return { ...live, uploading: null, runStatus: "running", queue: null, step: e.step ?? null, steps: e.steps ?? null, runValue: e.value };
    case "preview":
      return { ...live, preview: { run, node: e.node } };
    default:
      return live;
  }
}

/** A short human sentence for what is happening right now. */
export function describe(live) {
  if (live.ended === "failed" || live.error) return live.error?.message ?? "Failed";
  if (live.ended === "canceled") return "Canceled";
  if (live.ended === "succeeded") return "Done";
  if (live.approval) return "Waiting for your approval";
  if (live.uploading) return `Uploading ${live.uploading.files} file${live.uploading.files === 1 ? "" : "s"}`;
  if (live.runStatus === "queued") return live.queue ? `Queued (position ${live.queue})` : "Queued";
  if (live.runStatus === "running") return live.steps ? `${label(live.stage)}: step ${live.step}/${live.steps}` : `${label(live.stage)}`;
  return live.stage ? label(live.stage) : "Starting";
}

const LABELS = { hero: "Hero still", prepare: "Preparing clip", motion: "Motion transfer", finish: "Finishing", replay: "Replaying" };

export function label(stage) {
  if (!stage) return "";
  if (LABELS[stage]) return LABELS[stage];
  const anchor = /^anchor_(\d+)(_retry)?$/.exec(stage);
  if (anchor) return `Anchor ${anchor[1]}${anchor[2] ? " (re-roll)" : ""}`;
  const shoot = /^shoot_(\d+)$/.exec(stage);
  if (shoot) return `Shot ${shoot[1]}`;
  return stage.replace(/_/g, " ");
}
