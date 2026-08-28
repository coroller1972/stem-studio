export const STEM_NAMES = ["vocals", "drums", "bass", "other"] as const;
export const SPECTRAL_STEM_NAMES = ["vocals", "bass", "other"] as const;

export type StemName = (typeof STEM_NAMES)[number];
export type SpectralStemName = (typeof SPECTRAL_STEM_NAMES)[number];
export type SeparationQuality = "standard" | "high";
export type ProjectStatus = "empty" | "separating" | "loading" | "ready" | "error";
export type TransportStatus = "stopped" | "playing" | "paused";
export type TranscriptionTrack = "bass" | "drums";
export type BassTuning = "eadg" | "beadg";
export type BassTranscriptionEngine = "basic-pitch" | "torchcrepe";
export type TranscriptionStatus = "idle" | "processing" | "ready" | "error";
export type TranscriptionStage =
  | "loading_model"
  | "inference"
  | "beat_tracking"
  | "quantization"
  | "fretboard"
  | "export"
  | "completed";

export interface TempoBeat {
  beatIndex: number;
  timeSeconds: number;
}

export interface TempoMap {
  bpm: number;
  beats: TempoBeat[];
  timeSignature: { numerator: number; denominator: number };
  tempoCandidates?: number[];
}

export interface PitchBendPoint {
  timeOffsetSeconds: number;
  semitones: number;
}

export interface NoteEvent {
  id: string;
  detectedStartSeconds: number;
  detectedEndSeconds: number;
  quantizedStartBeat: number | null;
  quantizedDurationBeats: number | null;
  midiPitch: number;
  velocity: number;
  confidence: number | null;
  pitchBends?: PitchBendPoint[];
}

export type DrumInstrument =
  | "kick"
  | "snare"
  | "closed_hihat"
  | "open_hihat"
  | "ride"
  | "crash"
  | "high_tom"
  | "mid_tom"
  | "low_tom"
  | "other";

export interface DrumEvent {
  id: string;
  detectedTimeSeconds: number;
  quantizedBeat: number | null;
  instrument: DrumInstrument;
  velocity: number;
  confidence: number | null;
}

export interface TabNote {
  noteEventId: string;
  stringIndex: number;
  fret: number;
  startBeat: number;
  durationBeats: number;
}

export interface BassTranscription {
  schemaVersion: number;
  track: "bass";
  events: NoteEvent[];
  tab: TabNote[];
  tempoMap: TempoMap;
  tuning: number[];
  warnings: string[];
  modelId?: string;
  sourceEvents?: NoteEvent[];
}

export interface DrumTranscription {
  schemaVersion: number;
  track: "drums";
  events: DrumEvent[];
  tempoMap: TempoMap;
  warnings: string[];
  sourceEvents?: DrumEvent[];
}

export interface TranscriptionFiles<T extends BassTranscription | DrumTranscription> {
  eventsFile: string;
  midiFile: string;
  musicXmlFile: string;
  transcription: T;
}

export interface TrackTranscriptionState<T extends BassTranscription | DrumTranscription> {
  status: TranscriptionStatus;
  stage: TranscriptionStage | null;
  progress: number;
  message: string;
  error: string | null;
  result: TranscriptionFiles<T> | null;
}

export interface ProjectTranscriptions {
  bass: TrackTranscriptionState<BassTranscription>;
  drums: TrackTranscriptionState<DrumTranscription>;
}

export type StemPaths = Record<StemName, string>;

export interface SpectrogramData {
  width: number;
  height: number;
  minMidi: number;
  maxMidi: number;
  values: Uint8Array;
}

export interface StemState {
  volume: number;
  muted: boolean;
  solo: boolean;
}

export interface SourceMetadata {
  name: string;
  path: string;
  durationSeconds: number | null;
}

export type SeparationEvent =
  | { type: "progress"; progress: number; message: string }
  | { type: "completed"; stems: StemPaths }
  | { type: "error"; message: string; detail?: string };

export type TranscriptionEvent =
  | {
      type: "transcription_progress";
      track: TranscriptionTrack;
      stage: TranscriptionStage;
      progress: number;
      message: string;
    }
  | {
      type: "transcription_completed";
      track: "bass";
      result: TranscriptionFiles<BassTranscription>;
    }
  | {
      type: "transcription_completed";
      track: "drums";
      result: TranscriptionFiles<DrumTranscription>;
    }
  | { type: "transcription_error"; message: string; detail?: string };

export interface SeparationResult {
  projectId: string;
  projectPath: string;
  stems: StemPaths;
  qualityProfile: SeparationQuality;
}

export interface PortableSessionState {
  currentTimeSeconds: number;
  startMarkerSeconds: number;
  masterVolume: number;
  tracks: Record<StemName, StemState>;
}

export interface SavedSession {
  sessionPath: string;
  manifestPath: string;
}

export interface RestoredSession {
  sessionPath: string;
  manifestPath: string;
  sourceName: string;
  qualityProfile: SeparationQuality;
  stems: StemPaths;
  state: PortableSessionState;
  transcriptions: {
    bass: TranscriptionFiles<BassTranscription> | null;
    drums: TranscriptionFiles<DrumTranscription> | null;
  };
}
