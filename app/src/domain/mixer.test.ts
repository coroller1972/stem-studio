import { describe, expect, it } from "vitest";
import { calculateEffectiveGains, createDefaultTracks } from "./mixer";

describe("calculateEffectiveGains", () => {
  it("uses each non-muted track volume when no track is soloed", () => {
    const tracks = createDefaultTracks();
    tracks.vocals.volume = 0.42;
    tracks.drums.muted = true;

    expect(calculateEffectiveGains(tracks)).toEqual({
      vocals: 0.42,
      drums: 0,
      bass: 0.8,
      other: 0.8,
    });
  });

  it("only lets non-muted solo tracks through when any solo is active", () => {
    const tracks = createDefaultTracks();
    tracks.vocals.solo = true;
    tracks.drums.solo = true;
    tracks.drums.muted = true;

    expect(calculateEffectiveGains(tracks)).toEqual({
      vocals: 0.8,
      drums: 0,
      bass: 0,
      other: 0,
    });
  });

  it("clamps invalid volume bounds", () => {
    const tracks = createDefaultTracks();
    tracks.vocals.volume = 3;
    tracks.bass.volume = -1;
    const gains = calculateEffectiveGains(tracks);
    expect(gains.vocals).toBe(1);
    expect(gains.bass).toBe(0);
  });
});

