// The address bar: "#/lobby", "#/direct", "#/takes", or "#/takes/<take id>" for a take that travels as a link.

/** Parse a hash into its station and, when there is one, the take it points at. */
export function parseHash(hash, routes) {
  const m = /^#\/([a-z]+)(?:\/([A-Za-z0-9_.-]+))?/.exec(hash ?? "");
  const route = m && routes.has(m[1]) ? m[1] : null;
  return { route: route ?? "lobby", id: route ? m[2] ?? null : null }; // no room named: the Lobby, the first room
}

/** The link that opens a take, playing, with its receipt; the hosted copy answers the same address. */
export const takeLink = (id, { origin = globalThis.location?.origin ?? "", pathname = globalThis.location?.pathname ?? "/" } = {}) => `${origin}${pathname}#/takes/${id}`;
