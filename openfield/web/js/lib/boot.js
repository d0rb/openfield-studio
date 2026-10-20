// Choose the api for this page: the client-only Replay when the page is a static export,
// otherwise the HTTP api of the running app.

import { http } from "./api.js";
import { createStaticApi } from "./api-static.js";

export async function pickApi({ createStatic = createStaticApi, live = http } = {}) {
  return (await createStatic()) ?? live;
}
