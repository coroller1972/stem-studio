import type { ProjectTranscriptions, TempoBeat, TempoMap, TranscriptionTrack } from "./types";

/** The beats a metronome follows: what the iPhone package carries and what the desktop derives. */
export interface MetronomeTempo {
  bpm: number;
  beatsPerBar: number;
  beats: TempoBeat[];
  /** Where the tempo came from, shown to the user ("drums transcription", "manual tempo"…). */
  source: string;
}

/** "detected" is the engine's beat tracker, run on the four stems like for the iPhone export. */
export type TempoSourceId = TranscriptionTrack | "detected" | "manual";

export const MIN_BPM = 20;
export const MAX_BPM = 400;
export const MAX_BEATS_PER_BAR = 16;
export const DEFAULT_BEATS_PER_BAR = 4;
/** Transcriptions whose tempo the metronome may follow, in order of preference. */
const TRANSCRIPTION_SOURCES: readonly TranscriptionTrack[] = ["drums", "bass"];

export function isValidBpm(bpm: number): boolean {
  return Number.isFinite(bpm) && bpm >= MIN_BPM && bpm <= MAX_BPM;
}

export function isValidBeatsPerBar(beatsPerBar: number): boolean {
  return Number.isInteger(beatsPerBar) && beatsPerBar >= 1 && beatsPerBar <= MAX_BEATS_PER_BAR;
}

/**
 * A steady tempo whose bar starts at `downbeatSeconds`, with beats across the
 * whole song. It mirrors the manual tempo of engine/player_package.py
 * (`choose_tempo`): the downbeat is beat 0, earlier beats get negative indexes.
 */
export function manualTempo(
  bpm: number,
  downbeatSeconds: number,
  durationSeconds: number,
  beatsPerBar = DEFAULT_BEATS_PER_BAR,
): MetronomeTempo | null {
  if (!isValidBpm(bpm) || !isValidBeatsPerBar(beatsPerBar)) return null;
  if (!Number.isFinite(downbeatSeconds) || !(durationSeconds > 0)) return null;
  const period = 60 / bpm;
  const first = ((downbeatSeconds % period) + period) % period;
  const indexOffset = -Math.round((downbeatSeconds - first) / period);
  const count = Math.max(2, Math.floor((durationSeconds - first) / period) + 1);
  const beats = Array.from({ length: count }, (_, step) => ({
    beatIndex: indexOffset + step,
    timeSeconds: first + step * period,
  }));
  return { bpm, beatsPerBar, beats, source: "manual tempo" };
}

/**
 * Reads a tempo written by the engine (`tempo_payload` in engine/player_package.py),
 * from an iPhone package or the desktop's tempo detection. Damaged data gives null.
 */
export function parseMetronomeTempo(value: unknown, fallbackSource: string): MetronomeTempo | null {
  const tempo = record(value);
  if (!tempo || typeof tempo.bpm !== "number" || !isValidBpm(tempo.bpm) || !Array.isArray(tempo.beats)) return null;
  const beats: TempoBeat[] = [];
  for (const item of tempo.beats) {
    const beat = record(item);
    if (!beat || !Number.isInteger(beat.beatIndex) || typeof beat.timeSeconds !== "number" || !Number.isFinite(beat.timeSeconds)) {
      return null;
    }
    beats.push({ beatIndex: beat.beatIndex as number, timeSeconds: beat.timeSeconds });
  }
  if (beats.length < 2) return null;
  const beatsPerBar = typeof tempo.beatsPerBar === "number" && isValidBeatsPerBar(tempo.beatsPerBar)
    ? tempo.beatsPerBar
    : DEFAULT_BEATS_PER_BAR;
  return { bpm: tempo.bpm, beatsPerBar, beats, source: typeof tempo.source === "string" ? tempo.source : fallbackSource };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** The tempo of a transcription, with its time signature's numerator as the bar length. */
export function tempoFromMap(tempoMap: TempoMap | null | undefined, source: string): MetronomeTempo | null {
  if (!tempoMap || !isValidBpm(tempoMap.bpm) || !Array.isArray(tempoMap.beats)) return null;
  const beats = tempoMap.beats.filter(
    (beat) => Number.isInteger(beat.beatIndex) && Number.isFinite(beat.timeSeconds),
  );
  if (beats.length < 2) return null;
  const numerator = tempoMap.timeSignature?.numerator;
  const beatsPerBar = isValidBeatsPerBar(numerator) ? numerator : DEFAULT_BEATS_PER_BAR;
  return { bpm: tempoMap.bpm, beatsPerBar, beats, source };
}

export interface TempoChoice {
  /** The source in use: the preferred one when it has a tempo, else the first that does. */
  source: TempoSourceId;
  tempo: MetronomeTempo | null;
  /** Every source the user can pick; "manual" is always offered. */
  available: TempoSourceId[];
}

export interface ManualTempoInput {
  bpm: number | null;
  beatsPerBar: number;
  /** Song time of a bar's first beat. */
  downbeatSeconds: number;
}

export type TranscriptionTempoMaps = Partial<Record<TranscriptionTrack, TempoMap | null | undefined>>;

/** The tempo maps of the project's finished transcriptions. */
export function transcriptionTempoMaps(transcriptions: ProjectTranscriptions): TranscriptionTempoMaps {
  return {
    drums: transcriptions.drums.result?.transcription.tempoMap ?? null,
    bass: transcriptions.bass.result?.transcription.tempoMap ?? null,
  };
}

/**
 * Picks the metronome's tempo like the iPhone export: a transcription's beat
 * map when one exists (drums first, then bass, including a corrected tempo),
 * then the beat tracker's, otherwise the manual tempo.
 */
export function chooseTempo(
  preferred: TempoSourceId | null,
  maps: TranscriptionTempoMaps,
  detected: MetronomeTempo | null,
  manual: ManualTempoInput,
  durationSeconds: number,
): TempoChoice {
  const tempos: Partial<Record<Exclude<TempoSourceId, "manual">, MetronomeTempo>> = {};
  for (const track of TRANSCRIPTION_SOURCES) {
    const tempo = tempoFromMap(maps[track], `${track} transcription`);
    if (tempo) tempos[track] = tempo;
  }
  if (detected) tempos.detected = detected;
  const available: TempoSourceId[] = [
    ...([...TRANSCRIPTION_SOURCES, "detected"] as const).filter((source) => tempos[source]),
    "manual",
  ];
  const source = preferred && available.includes(preferred) ? preferred : available[0]!;
  if (source !== "manual") return { source, tempo: tempos[source]!, available };
  const tempo = manual.bpm === null
    ? null
    : manualTempo(manual.bpm, manual.downbeatSeconds, durationSeconds, manual.beatsPerBar);
  return { source, tempo, available };
}

const TAP_RESET_SECONDS = 2;
const MAX_TAPS = 16;

/** Adds a tap, starting over after a pause; only the latest taps are kept. */
export function addTap(taps: readonly number[], at: number): number[] {
  const last = taps.at(-1);
  const kept = last === undefined || at <= last || at - last > TAP_RESET_SECONDS ? [] : [...taps];
  kept.push(at);
  return kept.slice(-MAX_TAPS);
}

/**
 * Tempo from taps on successive beats. A least-squares line through the taps
 * averages out the finger's jitter; the first tap is taken as a bar's first
 * beat, so tapping along from "one" also places the bars.
 */
export function tapTempo(taps: readonly number[]): { bpm: number; downbeatSeconds: number } | null {
  if (taps.length < 3) return null;
  const meanIndex = (taps.length - 1) / 2;
  const meanTime = taps.reduce((sum, time) => sum + time, 0) / taps.length;
  let covariance = 0;
  let variance = 0;
  taps.forEach((time, index) => {
    covariance += (index - meanIndex) * (time - meanTime);
    variance += (index - meanIndex) ** 2;
  });
  const period = covariance / variance;
  if (!(period > 0)) return null;
  const bpm = Math.round((60 / period) * 10) / 10;
  if (!isValidBpm(bpm)) return null;
  return { bpm, downbeatSeconds: meanTime - period * meanIndex };
}
