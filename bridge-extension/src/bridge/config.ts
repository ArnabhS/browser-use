// M1: the bridge runs against a LOCAL backend only (no auth yet — see spec §10). Point this at your
// backend's /ws/bridge. A later milestone moves this to an options page + shared token.
export const BACKEND_WS = "ws://localhost:8000/ws/bridge";
export const CDP_VERSION = "1.3";
// Keep the MV3 service worker (and the socket) alive: WebSocket activity resets the ~30s idle timer
// on Chrome ≥116, so a periodic ping is enough while a tab is under control.
export const HEARTBEAT_MS = 20_000;
export const RECONNECT_MS = 3_000;
