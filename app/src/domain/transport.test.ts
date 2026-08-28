import { describe, expect, it } from "vitest";
import { clampTime, reduceTransport, type TransportSnapshot } from "./transport";

const initial: TransportSnapshot = {
  status: "stopped",
  currentTime: 0,
  duration: 180,
  startMarkerSeconds: 83.45,
};

describe("transport state", () => {
  it("starts explicitly from the distinct start marker", () => {
    const result = reduceTransport(initial, { type: "play-from-marker" });
    expect(result.status).toBe("playing");
    expect(result.currentTime).toBe(83.45);
    expect(result.startMarkerSeconds).toBe(83.45);
  });

  it("keeps the marker independent when seeking the playhead", () => {
    const result = reduceTransport(initial, { type: "seek", seconds: 120 });
    expect(result.currentTime).toBe(120);
    expect(result.startMarkerSeconds).toBe(83.45);
  });

  it("preserves position across play and pause transitions", () => {
    const playing = reduceTransport({ ...initial, currentTime: 42 }, { type: "play" });
    const paused = reduceTransport(playing, { type: "pause" });
    expect(playing.status).toBe("playing");
    expect(paused).toMatchObject({ status: "paused", currentTime: 42 });
  });

  it("returns to the marker on stop", () => {
    const result = reduceTransport(
      { ...initial, status: "playing", currentTime: 120 },
      { type: "stop" },
    );
    expect(result).toMatchObject({ status: "stopped", currentTime: 83.45 });
  });

  it("clamps seek and marker positions to the timeline", () => {
    expect(clampTime(-5, 180)).toBe(0);
    expect(clampTime(999, 180)).toBe(180);
    expect(reduceTransport(initial, { type: "set-marker", seconds: 999 }).startMarkerSeconds).toBe(
      180,
    );
  });
});

