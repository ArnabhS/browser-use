import { PROTOCOL_VERSION } from "@browser-agent/contracts";

// Scaffold service worker: confirms the contracts wiring loads in an MV3 context.
console.log(`[bridge] service worker loaded; wire protocol v${PROTOCOL_VERSION}`);
