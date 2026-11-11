import { describe, expect, it } from "vitest";
import { beatTime, buildMetronomeGrid, countIn, isDownbeat } from "./metronome";
import { addTap, chooseTempo, manualTempo, tapTempo, tempoFromMap } from "./metronomeTempo";
import type { TempoMap } from "./types";

const map = (bpm: number, numerator = 4, first = 0.5, count = 16): TempoMap => ({
  bpm,
  beats: Array.from({ length: count }, (_, index) => ({ beatIndex: index, timeSeconds: first + (index * 60) / bpm })),
  timeSignature: { numerator, denominator: 4 },
});

const NO_MANUAL = { bpm: null, beatsPerBar: 4, downbeatSeconds: 0 };

describe("manual tempo", () => {
  it("puts beat 0 on the downbeat and covers the whole song, like the iPhone export", () => {
    const tempo = manualTempo(120, 1.25, 10, 3)!;
    expect(tempo.source).toBe("manual tempo");
    expect(tempo.beats[0]).toEqual({ beatIndex: -2, timeSeconds: 0.25 });
    expect(tempo.beats.find((beat) => beat.beatIndex === 0)!.timeSeconds).toBeCloseTo(1.25, 9);
    expect(tempo.beats.at(-1)!.timeSeconds).toBeLessThanOrEqual(10);
    expect(tempo.beats).toHaveLength(20);

    const grid = buildMetronomeGrid(tempo.beats, tempo.beatsPerBar)!;
    expect(grid.bpm).toBeCloseTo(120, 6);
    expect(isDownbeat(grid, 0)).toBe(true);
    expect(isDownbeat(grid, 3)).toBe(true);
    expect(beatTime(grid, 3)).toBeCloseTo(2.75, 6);
  });

  it("accepts a downbeat late in the song", () => {
    const tempo = manualTempo(100, 61.3, 120)!;
    const downbeat = tempo.beats.find((beat) => beat.beatIndex === 0)!;
    expect(downbeat.timeSeconds).toBeCloseTo(61.3, 9);
    expect(tempo.beats[0]!.timeSeconds).toBeGreaterThanOrEqual(0);
    expect(tempo.beats[0]!.timeSeconds).toBeLessThan(0.6);
  });

  it("rejects tempos the grid cannot follow", () => {
    expect(manualTempo(10, 0, 60)).toBeNull();
    expect(manualTempo(500, 0, 60)).toBeNull();
    expect(manualTempo(120, 0, 0)).toBeNull();
    expect(manualTempo(120, Number.NaN, 60)).toBeNull();
    expect(manualTempo(120, 0, 60, 0)).toBeNull();
  });
});

describe("tempo source", () => {
  it("reads a transcription's beats and bar length", () => {
    expect(tempoFromMap(map(96, 3), "bass transcription")).toMatchObject({ bpm: 96, beatsPerBar: 3, source: "bass transcription" });
    expect(tempoFromMap(map(96, 0), "x")!.beatsPerBar).toBe(4);
    expect(tempoFromMap(map(96, 4, 0, 1), "x")).toBeNull();
    expect(tempoFromMap(null, "x")).toBeNull();
  });

  it("prefers the drums, then the bass, then the manual tempo", () => {
    const drums = map(120);
    const bass = map(121);
    expect(chooseTempo(null, { drums, bass }, NO_MANUAL, 60)).toMatchObject({
      source: "drums",
      tempo: { bpm: 120 },
      available: ["drums", "bass", "manual"],
    });
    expect(chooseTempo(null, { bass }, NO_MANUAL, 60)).toMatchObject({ source: "bass", available: ["bass", "manual"] });
    expect(chooseTempo(null, {}, NO_MANUAL, 60)).toEqual({ source: "manual", tempo: null, available: ["manual"] });
  });

  it("follows the user's choice while that source exists", () => {
    const manual = { bpm: 90, beatsPerBar: 4, downbeatSeconds: 0 };
    expect(chooseTempo("bass", { drums: map(120), bass: map(121) }, manual, 60).tempo!.bpm).toBe(121);
    expect(chooseTempo("manual", { drums: map(120) }, manual, 60).tempo!.bpm).toBe(90);
    // The bass transcription was cleared: fall back to what is left.
    expect(chooseTempo("bass", { drums: map(120) }, manual, 60).source).toBe("drums");
  });
});

describe("tap tempo", () => {
  it("starts over after a pause or a jump back in the song", () => {
    expect(addTap([1, 1.5], 2)).toEqual([1, 1.5, 2]);
    expect(addTap([1, 1.5], 4)).toEqual([4]);
    expect(addTap([10, 10.5], 3)).toEqual([3]);
    expect(addTap(Array.from({ length: 16 }, (_, index) => index * 0.5), 8)).toHaveLength(16);
  });

  it("averages jittery taps and places bar 1 on the first tap", () => {
    expect(tapTempo([1, 1.5])).toBeNull();
    const taps = [10.01, 10.49, 11.02, 11.5, 11.99, 12.51];
    const tapped = tapTempo(taps)!;
    expect(tapped.bpm).toBeCloseTo(120, 0);
    expect(tapped.downbeatSeconds).toBeCloseTo(10, 1);
    expect(tapTempo([1, 1, 1])).toBeNull();
  });

  it("counts in to a tapped tempo on its own bars", () => {
    const tapped = tapTempo([20, 20.5, 21, 21.5])!;
    const tempo = manualTempo(tapped.bpm, tapped.downbeatSeconds, 60)!;
    const grid = buildMetronomeGrid(tempo.beats, tempo.beatsPerBar)!;
    const result = countIn(grid, 24, 1);
    expect(result.clicks.map((click) => click.time)).toEqual([22, 22.5, 23, 23.5].map((time) => expect.closeTo(time, 6)));
    expect(result.clicks[0]!.accent).toBe(true);
  });
});
