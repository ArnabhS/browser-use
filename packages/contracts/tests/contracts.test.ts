import { describe, it, expect } from "vitest";
import { ObservationSchema } from "../src/generated/observation";
import { PROTOCOL_VERSION } from "../src/generated/version";

describe("Observation contract", () => {
  it("parses a valid observation", () => {
    const ok = ObservationSchema.parse({
      protocolVersion: PROTOCOL_VERSION,
      url: "https://example.com",
      title: "Example",
      viewport: { width: 1280, height: 800, scrollX: 0, scrollY: 0 },
      elements: [{ index: 1, role: "button", name: "Login" }],
      droppedCount: 0,
    });
    expect(ok.url).toBe("https://example.com");
  });

  it("rejects an observation with a wrong-typed url", () => {
    expect(() => ObservationSchema.parse({ url: 123, viewport: {} })).toThrow();
  });
});
