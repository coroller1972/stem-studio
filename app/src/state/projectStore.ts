import { create } from "zustand";
import { clampVolume, createDefaultTracks } from "../domain/mixer";
import type {
  BassTranscription,
  DrumTranscription,
  PortableSessionState,
  ProjectTranscriptions,
  ProjectStatus,
  SeparationQuality,
  SourceMetadata,
  StemName,
  StemPaths,
  StemState,
  TranscriptionFiles,
  TranscriptionStage,
  TranscriptionTrack,
  TransportStatus,
} from "../domain/types";
import { clampTime } from "../domain/transport";

interface ProjectState {
  source: SourceMetadata | null;
  projectPath: string | null;
  sessionPath: string | null;
  separationQuality: SeparationQuality | null;
  stems: StemPaths | null;
  status: ProjectStatus;
  transportStatus: TransportStatus;
  progress: number;
  statusMessage: string;
  errorMessage: string | null;
  currentTime: number;
  duration: number;
  startMarkerSeconds: number;
  masterVolume: number;
  tracks: Record<StemName, StemState>;
  waveforms: Partial<Record<StemName, Float32Array>>;
  transcriptions: ProjectTranscriptions;
  beginImport: (path: string) => void;
  setProgress: (progress: number, message: string) => void;
  setSeparated: (projectPath: string, stems: StemPaths, quality: SeparationQuality) => void;
  setSavedSession: (sessionPath: string) => void;
  restoreSession: (
    manifestPath: string,
    sessionPath: string,
    sourceName: string,
    stems: StemPaths,
    sessionState: PortableSessionState,
    transcriptions: {
      bass: TranscriptionFiles<BassTranscription> | null;
      drums: TranscriptionFiles<DrumTranscription> | null;
    },
    quality: SeparationQuality,
  ) => void;
  setReady: (duration: number, waveforms: Record<StemName, Float32Array>) => void;
  setError: (message: string) => void;
  reset: () => void;
  setTrack: (name: StemName, patch: Partial<StemState>) => void;
  setCurrentTime: (seconds: number) => void;
  setStartMarker: (seconds: number) => void;
  setMasterVolume: (volume: number) => void;
  setTransportStatus: (status: TransportStatus) => void;
  beginTranscription: (track: TranscriptionTrack) => void;
  setTranscriptionProgress: (
    track: TranscriptionTrack,
    stage: TranscriptionStage,
    progress: number,
    message: string,
  ) => void;
  setBassTranscription: (result: TranscriptionFiles<BassTranscription>) => void;
  setDrumTranscription: (result: TranscriptionFiles<DrumTranscription>) => void;
  setTranscriptionError: (track: TranscriptionTrack, message: string) => void;
}

const initialState = {
  source: null,
  projectPath: null,
  sessionPath: null,
  separationQuality: null,
  stems: null,
  status: "empty" as const,
  transportStatus: "stopped" as const,
  progress: 0,
  statusMessage: "Drop an MP3 or WAV to begin",
  errorMessage: null,
  currentTime: 0,
  duration: 0,
  startMarkerSeconds: 0,
  masterVolume: 1,
  tracks: createDefaultTracks(),
  waveforms: {},
  transcriptions: createDefaultTranscriptions(),
};

export const useProjectStore = create<ProjectState>((set) => ({
  ...initialState,
  beginImport: (path) =>
    set((state) => ({
      ...initialState,
      masterVolume: state.masterVolume,
      tracks: createDefaultTracks(),
      source: { path, name: fileNameFromPath(path), durationSeconds: null },
      status: "separating",
      statusMessage: "Preparing separation engine",
    })),
  setProgress: (progress, statusMessage) =>
    set({ progress: Math.min(1, Math.max(0, progress)), statusMessage }),
  setSeparated: (projectPath, stems, separationQuality) =>
    set({ projectPath, stems, separationQuality, status: "loading", statusMessage: "Decoding separated stems" }),
  setSavedSession: (sessionPath) => set({ sessionPath }),
  restoreSession: (manifestPath, sessionPath, sourceName, stems, sessionState, transcriptions, separationQuality) =>
    set({
      ...initialState,
      source: { path: manifestPath, name: sourceName, durationSeconds: null },
      projectPath: sessionPath,
      sessionPath,
      separationQuality,
      stems,
      status: "loading",
      statusMessage: "Loading saved session",
      currentTime: Math.max(0, sessionState.currentTimeSeconds),
      startMarkerSeconds: Math.max(0, sessionState.startMarkerSeconds),
      masterVolume: clampVolume(sessionState.masterVolume),
      tracks: cloneTracks(sessionState.tracks),
      transcriptions: restoredTranscriptionState(transcriptions),
    }),
  setReady: (duration, waveforms) =>
    set((state) => ({
      duration,
      currentTime: clampTime(state.currentTime, duration),
      startMarkerSeconds: clampTime(state.startMarkerSeconds, duration),
      waveforms,
      status: "ready",
      statusMessage: "Ready",
      source: state.source ? { ...state.source, durationSeconds: duration } : null,
    })),
  setError: (errorMessage) =>
    set({ status: "error", statusMessage: "Something went wrong", errorMessage }),
  reset: () =>
    set((state) => ({
      ...initialState,
      masterVolume: state.masterVolume,
      tracks: createDefaultTracks(),
      waveforms: {},
    })),
  setTrack: (name, patch) =>
    set((state) => ({
      tracks: { ...state.tracks, [name]: { ...state.tracks[name], ...patch } },
    })),
  setCurrentTime: (seconds) =>
    set((state) => ({ currentTime: clampTime(seconds, state.duration) })),
  setStartMarker: (seconds) =>
    set((state) => ({ startMarkerSeconds: clampTime(seconds, state.duration) })),
  setMasterVolume: (masterVolume) => set({ masterVolume: clampVolume(masterVolume) }),
  setTransportStatus: (transportStatus) => set({ transportStatus }),
  beginTranscription: (track) =>
    set((state) => ({
      transcriptions: {
        ...state.transcriptions,
        [track]: {
          ...state.transcriptions[track],
          status: "processing",
          stage: "loading_model",
          progress: 0,
          message: `Preparing ${track} transcription`,
          error: null,
        },
      },
    })),
  setTranscriptionProgress: (track, stage, progress, message) =>
    set((state) => ({
      transcriptions: {
        ...state.transcriptions,
        [track]: {
          ...state.transcriptions[track],
          status: "processing",
          stage,
          progress: Math.min(1, Math.max(0, progress)),
          message,
        },
      },
    })),
  setBassTranscription: (result) =>
    set((state) => ({
      transcriptions: {
        ...state.transcriptions,
        bass: {
          status: "ready",
          stage: "completed",
          progress: 1,
          message: "Bass transcription ready",
          error: null,
          result,
        },
      },
    })),
  setDrumTranscription: (result) =>
    set((state) => ({
      transcriptions: {
        ...state.transcriptions,
        drums: {
          status: "ready",
          stage: "completed",
          progress: 1,
          message: "Drum transcription ready",
          error: null,
          result,
        },
      },
    })),
  setTranscriptionError: (track, message) =>
    set((state) => ({
      transcriptions: {
        ...state.transcriptions,
        [track]: {
          ...state.transcriptions[track],
          status: "error",
          message: "Transcription failed",
          error: message,
        },
      },
    })),
}));

function createDefaultTranscriptions(): ProjectTranscriptions {
  const base = {
    status: "idle" as const,
    stage: null,
    progress: 0,
    message: "",
    error: null,
    result: null,
  };
  return { bass: { ...base }, drums: { ...base } };
}

function restoredTranscriptionState(transcriptions: {
  bass: TranscriptionFiles<BassTranscription> | null;
  drums: TranscriptionFiles<DrumTranscription> | null;
}): ProjectTranscriptions {
  const state = createDefaultTranscriptions();
  if (transcriptions.bass) {
    state.bass = {
      status: "ready",
      stage: "completed",
      progress: 1,
      message: "Bass transcription ready",
      error: null,
      result: transcriptions.bass,
    };
  }
  if (transcriptions.drums) {
    state.drums = {
      status: "ready",
      stage: "completed",
      progress: 1,
      message: "Drum transcription ready",
      error: null,
      result: transcriptions.drums,
    };
  }
  return state;
}

function fileNameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function cloneTracks(tracks: Record<StemName, StemState>): Record<StemName, StemState> {
  return {
    vocals: { ...tracks.vocals },
    drums: { ...tracks.drums },
    bass: { ...tracks.bass },
    other: { ...tracks.other },
  };
}
