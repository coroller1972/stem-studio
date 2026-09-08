import { useCallback, useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { EmptyState } from "./components/EmptyState";
import { ErrorView } from "./components/ErrorView";
import { FrequencyView } from "./components/FrequencyView";
import { Header } from "./components/Header";
import { ProcessingView } from "./components/ProcessingView";
import { Timeline } from "./components/Timeline";
import { Transport } from "./components/Transport";
import {
  BassTranscriptionView,
  DrumTranscriptionView,
  StudioTabs,
  type StudioTab,
} from "./components/TranscriptionWorkspace";
import { useAudioEngine } from "./hooks/useAudioEngine";
import { spectrogramRange } from "./audio/spectrogram";
import type {
  BassTranscription,
  BassTranscriptionEngine,
  BassTuning,
  DrumInstrument,
  DrumTranscription,
  SeparationQuality,
  SpectralStemName,
  SpectrogramData,
  TempoMap,
  TranscriptionFiles,
  TranscriptionTrack,
} from "./domain/types";
import { resolveTransportKeyboardShortcut } from "./domain/keyboardShortcuts";
import { isTauriRuntime, TauriSeparationService } from "./services/separationService";
import { TauriSessionService } from "./services/sessionService";
import { TauriTranscriptionService } from "./services/transcriptionService";
import { useProjectStore } from "./state/projectStore";
import { ProjectOperations } from "./services/projectOperations";

const AUDIO_EXTENSION = /\.(mp3|wav)$/i;

export default function App() {
  const service = useMemo(() => new TauriSeparationService(), []);
  const sessionService = useMemo(() => new TauriSessionService(), []);
  const transcriptionService = useMemo(() => new TauriTranscriptionService(), []);
  const audio = useAudioEngine();
  const operations = useMemo(() => new ProjectOperations(), []);
  const [projectBusy, setProjectBusy] = useState(false);
  useEffect(() => () => operations.dispose(), [operations]);
  const state = useProjectStore(useShallow((store) => ({
    status: store.status,
    progress: store.progress,
    statusMessage: store.statusMessage,
    errorMessage: store.errorMessage,
    duration: store.duration,
    startMarkerSeconds: store.startMarkerSeconds,
    masterVolume: store.masterVolume,
    tracks: store.tracks,
    waveforms: store.waveforms,
    transcriptions: store.transcriptions,
    source: store.source,
    transportStatus: store.transportStatus,
    beginImport: store.beginImport,
    reset: store.reset,
    restoreSession: store.restoreSession,
    setCurrentTime: store.setCurrentTime,
    setError: store.setError,
    setProgress: store.setProgress,
    setReady: store.setReady,
    setSavedSession: store.setSavedSession,
    setSeparated: store.setSeparated,
    setStartMarker: store.setStartMarker,
    setMasterVolume: store.setMasterVolume,
    setTrack: store.setTrack,
    beginTranscription: store.beginTranscription,
    setBassTranscription: store.setBassTranscription,
    setDrumTranscription: store.setDrumTranscription,
    setTranscriptionError: store.setTranscriptionError,
    setTranscriptionProgress: store.setTranscriptionProgress,
  })));
  const {
    beginImport,
    reset,
    restoreSession,
    setCurrentTime,
    setError,
    setProgress,
    setReady,
    setSavedSession,
    setSeparated,
    setStartMarker,
    setTrack,
    beginTranscription,
    setBassTranscription,
    setDrumTranscription,
    setTranscriptionError,
    setTranscriptionProgress,
  } = state;
  const [isDragging, setIsDragging] = useState(false);
  const [quality, setQuality] = useState<SeparationQuality>("standard");
  const [sessionFeedback, setSessionFeedback] = useState<SessionFeedback | null>(null);
  const [activeTab, setActiveTab] = useState<StudioTab>("mixer");
  const [bassTuning, setBassTuning] = useState<BassTuning>("beadg");
  const [bassEngine, setBassEngine] = useState<BassTranscriptionEngine>("basic-pitch");
  const [frequencyStem, setFrequencyStem] = useState<SpectralStemName>("vocals");

  const importPath = useCallback(
    async (path: string, signal: AbortSignal) => {
      if (!operations.isCurrent(signal)) return;
      if (!AUDIO_EXTENSION.test(path)) {
        setSessionFeedback({ kind: "error", message: "Please choose an MP3 or WAV audio file." });
        return;
      }
      operations.projectChanged();
      audio.clear();
      beginImport(path);
      setActiveTab("mixer");
      try {
        const result = await service.separate(path, quality, (event) => {
          if (!operations.isCurrent(signal)) return;
          if (event.type === "progress") setProgress(event.progress, event.message);
          if (event.type === "error") setError(event.message);
        }, signal);
        if (!operations.isCurrent(signal)) return;
        setSeparated(result.projectPath, result.stems, result.qualityProfile);
        await audio.load(result.stems, signal);
      } catch (error) {
        if (!operations.isCurrent(signal)) return;
        const message = error instanceof Error ? error.message : String(error);
        if (message.toLowerCase().includes("cancel")) reset();
        else setError(toUserMessage(message));
      }
    },
    [audio, beginImport, operations, quality, reset, service, setError, setProgress, setSeparated],
  );

  const runImport = useCallback(async (path?: string) => {
    const signal = operations.begin();
    if (!signal) return;
    setProjectBusy(true);
    try {
      if (!path && !isTauriRuntime()) {
        setError("File import is available in the Tauri desktop app. Run npm run tauri dev.");
        return;
      }
      const selectedPath = path ?? await service.chooseFile();
      if (selectedPath && operations.isCurrent(signal)) await importPath(selectedPath, signal);
    } catch (error) {
      if (operations.isCurrent(signal)) setSessionFeedback({ kind: "error", message: toSessionMessage(error, "Unable to open the audio file.") });
    } finally {
      operations.finish(signal);
      setProjectBusy(operations.busy);
    }
  }, [importPath, operations, service, setError]);

  const chooseFile = useCallback(() => runImport(), [runImport]);

  const saveSession = useCallback(async () => {
    if (!isTauriRuntime()) {
      setSessionFeedback({ kind: "error", message: "Sessions are available in the Tauri desktop app." });
      return;
    }
    const snapshot = useProjectStore.getState();
    if (snapshot.status !== "ready" || !snapshot.projectPath || !snapshot.source) return;
    const signal = operations.begin();
    if (!signal) return;
    setProjectBusy(true);
    try {
      const sessionPath =
        snapshot.sessionPath ?? (await sessionService.chooseSessionPath(snapshot.source.name));
      if (!sessionPath || !operations.isCurrent(signal)) return;
      const result = await sessionService.save(
        snapshot.projectPath,
        sessionPath,
        snapshot.source.name,
        snapshot.separationQuality ?? quality,
        {
          currentTimeSeconds: snapshot.currentTime,
          startMarkerSeconds: snapshot.startMarkerSeconds,
          masterVolume: snapshot.masterVolume,
          tracks: snapshot.tracks,
        },
      );
      if (!operations.isCurrent(signal)) return;
      setSavedSession(result.sessionPath);
      setSessionFeedback({ kind: "success", message: `Session saved in ${result.sessionPath}` });
    } catch (error) {
      if (!operations.isCurrent(signal)) return;
      setSessionFeedback({ kind: "error", message: toSessionMessage(error, "Unable to save session.") });
    } finally {
      operations.finish(signal);
      setProjectBusy(operations.busy);
    }
  }, [operations, quality, sessionService, setSavedSession]);

  const openSession = useCallback(async () => {
    if (!isTauriRuntime()) {
      setSessionFeedback({ kind: "error", message: "Sessions are available in the Tauri desktop app." });
      return;
    }
    const signal = operations.begin();
    if (!signal) return;
    setProjectBusy(true);
    try {
      const manifestPath = await sessionService.chooseManifest();
      if (!manifestPath || !operations.isCurrent(signal)) return;
      const restored = await sessionService.load(manifestPath);
      if (!operations.isCurrent(signal)) return;
      operations.projectChanged();
      audio.clear();
      restoreSession(
        restored.manifestPath,
        restored.sessionPath,
        restored.sourceName,
        restored.stems,
        restored.state,
        restored.transcriptions,
        restored.qualityProfile,
      );
      setActiveTab("mixer");
      setQuality(restored.qualityProfile);
      const restoredBassTuning = restored.transcriptions.bass?.transcription.tuning;
      if (restoredBassTuning) setBassTuning(restoredBassTuning.length === 5 ? "beadg" : "eadg");
      const restoredBassModel = restored.transcriptions.bass?.transcription.modelId;
      if (restoredBassModel?.startsWith("torchcrepe")) setBassEngine("torchcrepe");
      else if (restoredBassModel?.startsWith("spotify-basic-pitch")) setBassEngine("basic-pitch");
      await audio.load(restored.stems, signal);
      if (!operations.isCurrent(signal)) return;
      await audio.seek(restored.state.currentTimeSeconds);
      if (!operations.isCurrent(signal)) return;
      setSessionFeedback({ kind: "success", message: `Session restored: ${restored.sourceName}` });
    } catch (error) {
      if (!operations.isCurrent(signal)) return;
      const snapshot = useProjectStore.getState();
      if (snapshot.status === "loading") {
        snapshot.setError(toSessionMessage(error, "Unable to load the saved audio stems."));
      } else {
        setSessionFeedback({ kind: "error", message: toSessionMessage(error, "Unable to open session.") });
      }
    } finally {
      operations.finish(signal);
      setProjectBusy(operations.busy);
    }
  }, [audio, operations, restoreSession, sessionService]);

  const transcribe = useCallback(
    async (track: TranscriptionTrack) => {
      const snapshot = useProjectStore.getState();
      if (snapshot.status !== "ready" || !snapshot.projectPath) return;
      const version = operations.version;
      const isCurrent = () => operations.version === version;
      beginTranscription(track);
      setActiveTab(track);
      const onEvent = (event: import("./domain/types").TranscriptionEvent) => {
        if (isCurrent() && event.type === "transcription_progress" && event.track === track) {
          setTranscriptionProgress(track, event.stage, event.progress, event.message);
        }
      };
      try {
        if (track === "bass") {
          const result = await transcriptionService.transcribe(
            snapshot.projectPath,
            "bass",
            onEvent,
            bassTuning,
            bassEngine,
          );
          if (isCurrent()) setBassTranscription(result);
        } else {
          const result = await transcriptionService.transcribe(snapshot.projectPath, "drums", onEvent);
          if (isCurrent()) setDrumTranscription(result);
        }
      } catch (error) {
        if (!isCurrent()) return;
        const message = error instanceof Error ? error.message : String(error);
        setTranscriptionError(track, message || `${track} transcription failed.`);
      }
    },
    [
      beginTranscription,
      operations,
      bassEngine,
      bassTuning,
      setBassTranscription,
      setDrumTranscription,
      setTranscriptionError,
      setTranscriptionProgress,
      transcriptionService,
    ],
  );

  const requantize = useCallback(
    async (track: TranscriptionTrack, bpm: number, firstMeasureSeconds: number) => {
      const snapshot = useProjectStore.getState();
      if (snapshot.status !== "ready" || !snapshot.projectPath) return;
      const version = operations.version;
      const isCurrent = () => operations.version === version;
      beginTranscription(track);
      const onEvent = (event: import("./domain/types").TranscriptionEvent) => {
        if (isCurrent() && event.type === "transcription_progress" && event.track === track) {
          setTranscriptionProgress(track, event.stage, event.progress, event.message);
        }
      };
      try {
        if (track === "bass") {
          const result = await transcriptionService.requantize(
            snapshot.projectPath,
            "bass",
            bpm,
            firstMeasureSeconds,
            onEvent,
          );
          if (isCurrent()) setBassTranscription(result);
        } else {
          const result = await transcriptionService.requantize(
            snapshot.projectPath,
            "drums",
            bpm,
            firstMeasureSeconds,
            onEvent,
          );
          if (isCurrent()) setDrumTranscription(result);
        }
      } catch (error) {
        if (!isCurrent()) return;
        const message = error instanceof Error ? error.message : String(error);
        setTranscriptionError(track, message || `Unable to update ${track} timing.`);
      }
    },
    [
      beginTranscription,
      operations,
      setBassTranscription,
      setDrumTranscription,
      setTranscriptionError,
      setTranscriptionProgress,
      transcriptionService,
    ],
  );

  const exportTranscription = useCallback(
    async (path: string, name: string, extension: "mid" | "musicxml") => {
      try {
        const destination = await transcriptionService.exportFile(path, name, extension);
        if (destination) setSessionFeedback({ kind: "success", message: `Exported to ${destination}` });
      } catch (error) {
        setSessionFeedback({ kind: "error", message: toSessionMessage(error, "Unable to export transcription.") });
      }
    },
    [transcriptionService],
  );

  const cancel = useCallback(async () => {
    try {
      await operations.cancel(async () => {
        audio.clear();
        if (useProjectStore.getState().status === "separating") await service.cancel();
      });
      reset();
    } catch {
      setError("Unable to stop the separation process cleanly.");
    } finally {
      setProjectBusy(operations.busy);
    }
  }, [audio, operations, reset, service, setError]);

  useEffect(() => {
    if (!isTauriRuntime()) return;
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (disposed) return;
        if (event.payload.type === "over") setIsDragging(true);
        if (event.payload.type === "leave") setIsDragging(false);
        if (event.payload.type === "drop") {
          setIsDragging(false);
          const [path] = event.payload.paths;
          if (path) void runImport(path);
        }
      })
      .then((unlisten) => {
        if (disposed) unlisten();
        else cleanup = unlisten;
      })
      .catch((error) => {
        if (!disposed) setSessionFeedback({ kind: "error", message: toSessionMessage(error, "Unable to enable file drop.") });
      });
    return () => { disposed = true; cleanup?.(); };
  }, [runImport]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      const shortcut = resolveTransportKeyboardShortcut(event);
      const snapshot = useProjectStore.getState();
      if (!shortcut || snapshot.status !== "ready") return;

      event.preventDefault();
      if (shortcut.type === "toggle-playback") {
        void audio.togglePlayback();
        return;
      }
      if (shortcut.type === "seek-relative") {
        void audio.seek(snapshot.currentTime + shortcut.deltaSeconds);
        return;
      }
      void audio.seek(snapshot.startMarkerSeconds);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [audio]);

  useEffect(() => {
    if (!sessionFeedback) return;
    const timeout = window.setTimeout(() => setSessionFeedback(null), 5_000);
    return () => window.clearTimeout(timeout);
  }, [sessionFeedback]);

  useEffect(() => {
    const demo = new URLSearchParams(window.location.search).get("demo");
    if (isTauriRuntime() || demo === null) return;
    const duration = 258.22;
    beginImport("/demo/midnight-drive.mp3");
    setSeparated("/demo", {
      vocals: "/demo/vocals.wav",
      drums: "/demo/drums.wav",
      bass: "/demo/bass.wav",
      other: "/demo/other.wav",
    }, "high");
    setReady(duration, createDemoWaveforms());
    setCurrentTime(83.45);
    setStartMarker(80);
    setTrack("vocals", { volume: 0.82 });
    setTrack("drums", { volume: 0.76 });
    setTrack("bass", { volume: 0.88 });
    setTrack("other", { volume: 0.7 });
    if (demo === "transcription") {
      const transcriptions = createDemoTranscriptions();
      setBassTranscription(transcriptions.bass);
      setDrumTranscription(transcriptions.drums);
    }
  }, []); // Demo-only seed state.

  return (
    <div className="app-shell">
      <Header
        fileName={state.source?.name ?? null}
        quality={quality}
        disabled={projectBusy || state.status === "separating" || state.status === "loading"}
        canSaveSession={state.status === "ready"}
        onImport={() => void chooseFile()}
        onOpenSession={() => void openSession()}
        onSaveSession={() => void saveSession()}
        onQualityChange={setQuality}
      />
      {state.status === "empty" ? (
        <EmptyState isDragging={isDragging} onImport={() => void chooseFile()} />
      ) : null}
      {state.status === "separating" || state.status === "loading" ? (
        <ProcessingView
          fileName={state.source?.name ?? "Audio file"}
          progress={state.status === "loading" ? 1 : state.progress}
          message={state.statusMessage}
          quality={quality}
          onCancel={() => void cancel()}
        />
      ) : null}
      {state.status === "error" ? (
        <ErrorView message={state.errorMessage ?? "An unexpected error occurred."} onReset={state.reset} />
      ) : null}
      {state.status === "ready" ? (
        <main className="studio-view">
          <div className="studio-main">
            <StudioTabs
              active={activeTab}
              bassStatus={state.transcriptions.bass.status}
              drumStatus={state.transcriptions.drums.status}
              onChange={setActiveTab}
            />
            {activeTab === "mixer" ? (
              <Timeline
                duration={state.duration}
                startMarkerSeconds={state.startMarkerSeconds}
                tracks={state.tracks}
                waveforms={state.waveforms}
                transcriptions={state.transcriptions}
                onTrackChange={state.setTrack}
                onSeek={(seconds) => void audio.seek(seconds)}
                onMarkerChange={state.setStartMarker}
                onTranscribe={(track) => void transcribe(track)}
              />
            ) : activeTab === "frequency" ? (
              <FrequencyView
                duration={state.duration}
                followPlayback={state.transportStatus === "playing"}
                selectedStem={frequencyStem}
                onStemChange={setFrequencyStem}
                onSeek={(seconds) => void audio.seek(seconds)}
                loadSpectrogram={(stem) =>
                  isBrowserDemo() ? Promise.resolve(createDemoSpectrogram(stem)) : audio.getSpectrogram(stem)
                }
              />
            ) : activeTab === "bass" ? (
              <BassTranscriptionView
                state={state.transcriptions.bass}
                followPlayback={state.transportStatus === "playing"}
                tuning={bassTuning}
                onTuningChange={setBassTuning}
                engine={bassEngine}
                onEngineChange={setBassEngine}
                onTranscribe={() => void transcribe("bass")}
                startMarkerSeconds={state.startMarkerSeconds}
                onRequantize={(bpm, firstMeasureSeconds) =>
                  void requantize("bass", bpm, firstMeasureSeconds)
                }
                onSeek={(seconds) => void audio.seek(seconds)}
                onExport={(path, name, extension) => void exportTranscription(path, name, extension)}
              />
            ) : (
              <DrumTranscriptionView
                state={state.transcriptions.drums}
                followPlayback={state.transportStatus === "playing"}
                onTranscribe={() => void transcribe("drums")}
                startMarkerSeconds={state.startMarkerSeconds}
                onRequantize={(bpm, firstMeasureSeconds) =>
                  void requantize("drums", bpm, firstMeasureSeconds)
                }
                onSeek={(seconds) => void audio.seek(seconds)}
                onExport={(path, name, extension) => void exportTranscription(path, name, extension)}
              />
            )}
          </div>
          <Transport
            status={state.transportStatus}
            duration={state.duration}
            marker={state.startMarkerSeconds}
            masterVolume={state.masterVolume}
            onToggle={() => void audio.togglePlayback()}
            onReturnToMarker={() => void audio.seek(state.startMarkerSeconds)}
            onPlayFromMarker={() => void audio.playFromMarker()}
            onSetMarker={() => state.setStartMarker(useProjectStore.getState().currentTime)}
            onMasterVolumeChange={state.setMasterVolume}
          />
        </main>
      ) : null}
      {isDragging && state.status !== "empty" ? <div className="drop-overlay">Drop audio to import</div> : null}
      {sessionFeedback ? (
        <div
          className={`session-feedback session-feedback-${sessionFeedback.kind}`}
          role={sessionFeedback.kind === "error" ? "alert" : "status"}
        >
          {sessionFeedback.message}
        </div>
      ) : null}
    </div>
  );
}

interface SessionFeedback {
  kind: "success" | "error";
  message: string;
}

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}

function toUserMessage(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("cancel")) return "Stem separation was cancelled.";
  if (lower.includes("high-quality engine") || lower.includes("python 3.10")) {
    return "High quality requires Python 3.10+ and the latest engine dependencies.";
  }
  if (lower.includes("space") || lower.includes("disk")) return "Not enough disk space to separate this file.";
  if (lower.includes("decode") || lower.includes("audio")) return "Unable to decode this audio file.";
  if (lower.includes("engine") || lower.includes("sidecar")) return "Separation process terminated unexpectedly.";
  return "Stem separation failed. Check the application logs for technical details.";
}

function toSessionMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : String(error);
  return message && message !== "undefined" ? message : fallback;
}

function createDemoWaveforms() {
  const create = (seed: number) => {
    const values = new Float32Array(700);
    let current = seed;
    for (let index = 0; index < values.length; index += 1) {
      current = (current * 1_664_525 + 1_013_904_223) % 4_294_967_296;
      const noise = current / 4_294_967_296;
      values[index] = 0.12 + noise * 0.65 * (0.72 + Math.sin(index / 29) * 0.28);
    }
    return values;
  };
  return { vocals: create(11), drums: create(23), bass: create(37), other: create(51) };
}

function createDemoTranscriptions(): {
  bass: TranscriptionFiles<BassTranscription>;
  drums: TranscriptionFiles<DrumTranscription>;
} {
  const tempoMap: TempoMap = {
    bpm: 108,
    beats: Array.from({ length: 12 }, (_, beatIndex) => ({ beatIndex, timeSeconds: 80 + beatIndex / 1.8 })),
    timeSignature: { numerator: 4, denominator: 4 },
  };
  const pitches = [40, 43, 45, 47, 45, 43, 40, 38];
  const positions: Array<readonly [number, number]> = [[3, 2], [3, 5], [2, 0], [2, 2], [2, 0], [3, 5], [3, 2], [3, 0]];
  const bassEvents = pitches.map((midiPitch, index) => ({
    id: `demo-bass-${index}`,
    detectedStartSeconds: 80 + index * 0.55,
    detectedEndSeconds: 80.45 + index * 0.55,
    quantizedStartBeat: index,
    quantizedDurationBeats: 0.75,
    midiPitch,
    velocity: 94,
    confidence: 0.91,
  }));
  const bass: BassTranscription = {
    schemaVersion: 1,
    track: "bass",
    events: bassEvents,
    tab: bassEvents.map((event, index) => {
      const [stringIndex, fret] = positions[index]!;
      return { noteEventId: event.id, stringIndex, fret, startBeat: index, durationBeats: 0.75 };
    }),
    tempoMap,
    tuning: [23, 28, 33, 38, 43],
    warnings: [],
  };
  const drumPattern: Array<[number, DrumInstrument]> = [
    [0, "kick"], [0, "closed_hihat"], [0.5, "closed_hihat"], [1, "snare"],
    [1, "closed_hihat"], [1.5, "closed_hihat"], [2, "kick"], [2, "closed_hihat"],
    [2.5, "kick"], [2.5, "closed_hihat"], [3, "snare"], [3, "closed_hihat"],
    [3.5, "closed_hihat"], [4, "kick"], [4, "crash"], [5, "snare"],
  ];
  const drums: DrumTranscription = {
    schemaVersion: 1,
    track: "drums",
    events: drumPattern.map(([quantizedBeat, instrument], index) => ({
      id: `demo-drums-${index}`,
      detectedTimeSeconds: 80 + quantizedBeat / 1.8,
      quantizedBeat,
      instrument,
      velocity: instrument === "closed_hihat" ? 80 : 105,
      confidence: 0.89,
    })),
    tempoMap,
    warnings: ["Five-class drum transcription groups detailed cymbal and tom articulations."],
  };
  return {
    bass: { eventsFile: "/demo/bass.json", midiFile: "/demo/bass.mid", musicXmlFile: "/demo/bass.musicxml", transcription: bass },
    drums: { eventsFile: "/demo/drums.json", midiFile: "/demo/drums.mid", musicXmlFile: "/demo/drums.musicxml", transcription: drums },
  };
}

function isBrowserDemo(): boolean {
  return !isTauriRuntime() && new URLSearchParams(window.location.search).has("demo");
}

function createDemoSpectrogram(stem: SpectralStemName): SpectrogramData {
  const width = 1_200;
  const { minMidi, maxMidi } = spectrogramRange(stem);
  const height = maxMidi - minMidi + 1;
  const values = new Uint8Array(width * height);
  const stemOffset = stem === "bass" ? -19 : stem === "other" ? 3 : 0;

  for (let column = 0; column < width; column += 1) {
    const phrase = Math.floor(column / 48) % 8;
    const fundamental = 58 + stemOffset + [0, 2, 4, 7, 4, 2, -1, 0][phrase]! + Math.sin(column / 31) * 0.7;
    for (let row = 0; row < height; row += 1) {
      const midi = maxMidi - row;
      const harmonic = Math.max(
        Math.exp(-((midi - fundamental) ** 2) / 1.5),
        Math.exp(-((midi - (fundamental + 12)) ** 2) / 2.5) * 0.7,
        Math.exp(-((midi - (fundamental + 19)) ** 2) / 3.5) * 0.42,
      );
      const texture = stem === "other" ? Math.max(0, Math.sin(column / 17 + midi * 0.9)) * 0.18 : 0;
      const envelope = 0.58 + Math.max(0, Math.sin(column / 9)) * 0.42;
      values[column * height + row] = Math.round(255 * Math.min(1, harmonic * envelope + texture));
    }
  }
  return { width, height, minMidi, maxMidi, values };
}
