import { describe, expect, it } from "vitest";
import { parseDetectedTempo } from "./tempoService";

describe("tempo detection result", () => {
  it("returns the detected beats, or null for a song without a steady tempo", () => {
    const result = parseDetectedTempo({
      bpm: 120,
      beatsPerBar: 4,
      beats: [{ beatIndex: 0, timeSeconds: 0.5 }, { beatIndex: 1, timeSeconds: 1 }],
      source: "beat tracker",
    });
    expect(result).toMatchObject({ bpm: 120, source: "beat tracker" });
    expect(parseDetectedTempo(null)).toBeNull();
  });

  it("rejects a malformed engine answer", () => {
    expect(() => parseDetectedTempo({ bpm: "fast" })).toThrow(/invalid tempo/);
  });
});
