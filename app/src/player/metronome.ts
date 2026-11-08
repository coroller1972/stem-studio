import type { TempoBeat } from "../domain/types";

export interface MetronomeClick {
  /** Song time in seconds; count-in clicks fall before the playback start. */
  time: number;
  accent: boolean;
}

export interface MetronomeGrid {
  bpm: number;
  beatsPerBar: number;
  /** Beat indexes run 0, 1, 2… from a bar's first beat; times are smoothed. */
  indexes: number[];
  times: number[];
  /** Beat lengths used to extend the grid before the first and after the last beat. */
  startPeriod: number;
  endPeriod: number;
}

const SMOOTHING_RADIUS = 4;
/** Beats further than this share of a beat from their neighbours' pulse are ignored. */
const OUTLIER_FRACTION = 0.2;
/** A start marker this close after a beat counts in to that beat. */
const START_TOLERANCE_SECONDS = 0.03;

/**
 * Builds the click grid from detected beats. Beat trackers place beats on
 * analysis frames (about 23 ms apart), so each beat is re-estimated from its
 * neighbours and their local beat length: the click stays steady yet still
 * follows tempo changes.
 */
export function buildMetronomeGrid(beats: readonly TempoBeat[], beatsPerBar: number): MetronomeGrid | null {
  const sorted = [...beats]
    .filter((beat) => Number.isFinite(beat.timeSeconds) && Number.isInteger(beat.beatIndex))
    .sort((left, right) => left.beatIndex - right.beatIndex)
    .filter((beat, index, all) => index === 0 || beat.beatIndex !== all[index - 1]!.beatIndex);
  if (sorted.length < 2 || !Number.isInteger(beatsPerBar) || beatsPerBar < 1) return null;

  const indexes = sorted.map((beat) => beat.beatIndex);
  const rawPeriods = periodsOf(indexes, sorted.map((beat) => beat.timeSeconds));
  if (rawPeriods.some((period) => !(period > 0))) return null;
  const times = sorted.map((beat, position) => {
    const from = Math.max(0, position - SMOOTHING_RADIUS);
    const to = Math.min(sorted.length - 1, position + SMOOTHING_RADIUS);
    const window = sorted.slice(from, to + 1);
    // Medians first set aside a spurious beat, common in a song's intro; a
    // least-squares line through the rest then averages out the frame steps,
    // which a median alone would keep (and so misread 150 BPM as 152).
    const period = median(rawPeriods.slice(from, to));
    const anchor = median(window.map((other) => other.timeSeconds + (beat.beatIndex - other.beatIndex) * period));
    const kept = window.filter(
      (other) => Math.abs(other.timeSeconds - anchor - (other.beatIndex - beat.beatIndex) * period) < OUTLIER_FRACTION * period,
    );
    if (kept.length < 2) return anchor;
    const { slope, intercept } = fitLine(kept);
    return intercept + slope * beat.beatIndex;
  });
  const periods = periodsOf(indexes, times);
  if (periods.some((period) => !(period > 0))) return null;
  const bpm = 60 / median(periods);
  if (!Number.isFinite(bpm) || bpm < 20 || bpm > 400) return null;
  return {
    bpm,
    beatsPerBar,
    indexes,
    times,
    startPeriod: median(periods.slice(0, 2 * SMOOTHING_RADIUS)),
    endPeriod: median(periods.slice(-2 * SMOOTHING_RADIUS)),
  };
}

/** Time of beat `index`, extrapolated at the edge tempo outside the detected range. */
export function beatTime(grid: MetronomeGrid, index: number): number {
  const { indexes, times } = grid;
  const last = indexes.length - 1;
  if (index <= indexes[0]!) return times[0]! - (indexes[0]! - index) * grid.startPeriod;
  if (index >= indexes[last]!) return times[last]! + (index - indexes[last]!) * grid.endPeriod;
  let low = 0;
  let high = last;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (indexes[middle]! <= index) low = middle;
    else high = middle;
  }
  const fraction = (index - indexes[low]!) / (indexes[high]! - indexes[low]!);
  return times[low]! + fraction * (times[high]! - times[low]!);
}

/** The first beat index whose time is at or after `seconds`. */
export function firstBeatAtOrAfter(grid: MetronomeGrid, seconds: number): number {
  const period = 60 / grid.bpm;
  let index = grid.indexes[0]! + Math.floor((seconds - grid.times[0]!) / period);
  if (seconds >= grid.times[0]! && seconds <= grid.times.at(-1)!) {
    // Inside the detected range the tempo can drift: search from a close guess.
    index = grid.indexes[Math.max(0, lowerBound(grid.times, seconds) - 1)]!;
  }
  while (beatTime(grid, index) < seconds) index += 1;
  while (beatTime(grid, index - 1) >= seconds) index -= 1;
  return index;
}

export function isDownbeat(grid: MetronomeGrid, index: number): boolean {
  return ((index % grid.beatsPerBar) + grid.beatsPerBar) % grid.beatsPerBar === 0;
}

/** Clicks for every beat in [from, to). */
export function songClicks(grid: MetronomeGrid, from: number, to: number): MetronomeClick[] {
  const clicks: MetronomeClick[] = [];
  for (let index = firstBeatAtOrAfter(grid, from); ; index += 1) {
    const time = beatTime(grid, index);
    if (time >= to) break;
    clicks.push({ time, accent: isDownbeat(grid, index) });
  }
  return clicks;
}

export interface CountIn {
  /** How long playback waits for the count-in before the start position plays. */
  leadInSeconds: number;
  clicks: MetronomeClick[];
}

/**
 * Counts `bars` bars into the song's own grid: the clicks continue the beats
 * backwards from the first beat at the start position, so the band comes in
 * in time even when the start marker sits mid-bar.
 */
export function countIn(grid: MetronomeGrid, startSeconds: number, bars: number): CountIn {
  if (bars <= 0) return { leadInSeconds: 0, clicks: [] };
  const target = firstBeatAtOrAfter(grid, startSeconds - START_TOLERANCE_SECONDS);
  const targetTime = beatTime(grid, target);
  const period = targetTime - beatTime(grid, target - 1);
  const count = bars * grid.beatsPerBar;
  const clicks = Array.from({ length: count }, (_, step) => {
    const offset = count - step;
    return { time: targetTime - offset * period, accent: isDownbeat(grid, target - offset) };
  });
  return { leadInSeconds: Math.max(0, startSeconds - clicks[0]!.time), clicks };
}

function fitLine(beats: readonly TempoBeat[]): { slope: number; intercept: number } {
  const meanIndex = beats.reduce((sum, beat) => sum + beat.beatIndex, 0) / beats.length;
  const meanTime = beats.reduce((sum, beat) => sum + beat.timeSeconds, 0) / beats.length;
  let covariance = 0;
  let variance = 0;
  for (const beat of beats) {
    covariance += (beat.beatIndex - meanIndex) * (beat.timeSeconds - meanTime);
    variance += (beat.beatIndex - meanIndex) ** 2;
  }
  const slope = covariance / variance;
  return { slope, intercept: meanTime - slope * meanIndex };
}

function periodsOf(indexes: readonly number[], times: readonly number[]): number[] {
  return times.slice(1).map((time, position) => (time - times[position]!) / (indexes[position + 1]! - indexes[position]!));
}

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2;
}

function lowerBound(values: readonly number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (values[middle]! < target) low = middle + 1;
    else high = middle;
  }
  return low;
}
