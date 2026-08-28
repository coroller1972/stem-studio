import { describe, expect, it } from "vitest";
import { parseSeparationEvent } from "./sidecarEvents";

describe("parseSeparationEvent", () => {
  it("parses and clamps a progress event", () => {
    expect(
      parseSeparationEvent('{"type":"progress","progress":1.4,"message":"Separating audio"}'),
    ).toEqual({ type: "progress", progress: 1, message: "Separating audio" });
  });

  it("parses a completed stem map", () => {
    const event = parseSeparationEvent(
      '{"type":"completed","stems":{"vocals":"/v.wav","drums":"/d.wav","bass":"/b.wav","other":"/o.wav"}}',
    );
    expect(event).toEqual({
      type: "completed",
      stems: {
        vocals: "/v.wav",
        drums: "/d.wav",
        bass: "/b.wav",
        other: "/o.wav",
      },
    });
  });

  it("ignores human logs, malformed events, and incomplete stems", () => {
    expect(parseSeparationEvent("Downloading model: 38%")) .toBeNull();
    expect(parseSeparationEvent('{"type":"progress","progress":"nope"}')).toBeNull();
    expect(parseSeparationEvent('{"type":"completed","stems":{"vocals":"/v.wav"}}')).toBeNull();
  });

  it("keeps a structured user error and optional detail", () => {
    expect(
      parseSeparationEvent(
        '{"type":"error","message":"Stem separation failed.","detail":"mps op unavailable"}',
      ),
    ).toEqual({
      type: "error",
      message: "Stem separation failed.",
      detail: "mps op unavailable",
    });
  });
});

