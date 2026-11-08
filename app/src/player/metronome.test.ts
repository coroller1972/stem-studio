import { describe, expect, it } from "vitest";
import { beatTime, buildMetronomeGrid, countIn, firstBeatAtOrAfter, songClicks } from "./metronome";

const steady = (bpm: number, first: number, count: number, firstIndex = 0) =>
  Array.from({ length: count }, (_, step) => ({ beatIndex: firstIndex + step, timeSeconds: first + (step * 60) / bpm }));

describe("metronome grid", () => {
  it("smooths frame-quantized beats into a steady click", () => {
    const frame = 512 / 22050;
    const jittered = steady(150, 1, 40).map((beat) => ({
      ...beat,
      timeSeconds: Math.round(beat.timeSeconds / frame) * frame,
    }));
    const grid = buildMetronomeGrid(jittered, 4)!;
    expect(grid.bpm).toBeCloseTo(150, 0);
    const exact = steady(150, 1, 40);
    const errors = grid.times.slice(4, -4).map((time, index) => Math.abs(time - exact[index + 4]!.timeSeconds));
    expect(Math.max(...errors)).toBeLessThan(0.006);
  });

  it("follows a tempo change instead of averaging it away", () => {
    const first = steady(120, 0, 20);
    const second = steady(160, first.at(-1)!.timeSeconds + 60 / 160, 20, 20);
    const grid = buildMetronomeGrid([...first, ...second], 4)!;
    expect(beatTime(grid, 5)).toBeCloseTo(2.5, 3);
    expect(beatTime(grid, 35) - beatTime(grid, 34)).toBeCloseTo(60 / 160, 3);
  });

  it("extrapolates beyond the detected beats and accents each bar's first beat", () => {
    const grid = buildMetronomeGrid(steady(120, 2, 8, -1), 4)!;
    expect(beatTime(grid, -3)).toBeCloseTo(1, 6);
    expect(beatTime(grid, 20)).toBeCloseTo(12.5, 6);
    expect(firstBeatAtOrAfter(grid, 1.01)).toBe(-2);
    expect(songClicks(grid, 2.4, 4.6)).toEqual([
      { time: expect.closeTo(2.5, 6), accent: true },
      { time: expect.closeTo(3, 6), accent: false },
      { time: expect.closeTo(3.5, 6), accent: false },
      { time: expect.closeTo(4, 6), accent: false },
      { time: expect.closeTo(4.5, 6), accent: true },
    ]);
  });

  it("ignores a spurious beat in the intro, for the grid and the count-in", () => {
    // Measured on a real song: the tracker's first beat comes 0.51 s before a 0.395 s pulse.
    const beats = [{ beatIndex: -1, timeSeconds: 0.093 }, ...steady(60 / 0.395, 0.604, 30)];
    const grid = buildMetronomeGrid(beats, 4)!;
    expect(beatTime(grid, -1)).toBeCloseTo(0.209, 3);
    expect(beatTime(grid, 1) - beatTime(grid, 0)).toBeCloseTo(0.395, 3);
    const clicks = countIn(grid, 0, 1).clicks.map((click) => click.time);
    expect(clicks[1]! - clicks[0]!).toBeCloseTo(0.395, 3);
  });

  it("rejects too few beats", () => {
    expect(buildMetronomeGrid([{ beatIndex: 0, timeSeconds: 1 }], 4)).toBeNull();
  });
});

describe("count-in", () => {
  const grid = buildMetronomeGrid(steady(120, 0, 40), 4)!;

  it("counts one bar into a start marker on a downbeat", () => {
    const result = countIn(grid, 4, 1);
    expect(result.leadInSeconds).toBeCloseTo(2, 6);
    expect(result.clicks.map((click) => click.time)).toEqual([2, 2.5, 3, 3.5].map((time) => expect.closeTo(time, 6)));
    expect(result.clicks.map((click) => click.accent)).toEqual([true, false, false, false]);
  });

  it("keeps the song's bar when the marker sits mid-bar or just before a beat", () => {
    const result = countIn(grid, 4.8, 1);
    // The next beat is beat 10 at 5 s, the third beat of its bar.
    expect(result.clicks.map((click) => click.time)).toEqual([3, 3.5, 4, 4.5].map((time) => expect.closeTo(time, 6)));
    expect(result.clicks.map((click) => click.accent)).toEqual([false, false, true, false]);
    expect(result.leadInSeconds).toBeCloseTo(1.8, 6);
  });

  it("treats a marker just after a beat as that beat and counts before the song starts", () => {
    expect(countIn(grid, 4.02, 2).clicks[0]!.time).toBeCloseTo(0, 6);
    const fromStart = countIn(grid, 0, 1);
    expect(fromStart.clicks[0]!.time).toBeCloseTo(-2, 6);
    expect(fromStart.leadInSeconds).toBeCloseTo(2, 6);
    expect(countIn(grid, 4, 0)).toEqual({ leadInSeconds: 0, clicks: [] });
  });
});
