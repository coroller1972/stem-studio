import type { ProjectTranscriptions, TempoBeat, TempoMap, TranscriptionTrack } from "./types";

/** The beats a metronome follows: what the iPhone package carries and what the desktop derives. */
export interface MetronomeTempo {
  bpm: number;
  beatsPerBar: number;
  beats: TempoBeat[];
  /** Where the tempo came from, shown to the user ("drums transcription", "manual tempo"…). */
  source: string;
}

export type TempoSourceId = TranscriptionTrack | "manual";

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
 * Picks the metronome's tempo: a transcription's beat map when one exists
 * (drums first, then bass), otherwise the manual tempo.
 */
export function chooseTempo(
  preferred: TempoSourceId | null,
  maps: TranscriptionTempoMaps,
  manual: ManualTempoInput,
  durationSeconds: number,
): TempoChoice {
  const tempos: Partial<Record<TranscriptionTrack, MetronomeTempo>> = {};
  for (const track of TRANSCRIPTION_SOURCES) {
    const tempo = tempoFromMap(maps[track], `${track} transcription`);
    if (tempo) tempos[track] = tempo;
  }
  const available: TempoSourceId[] = [...TRANSCRIPTION_SOURCES.filter((track) => tempos[track]), "manual"];
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
