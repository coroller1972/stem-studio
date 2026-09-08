import { Download, Music2, RefreshCw, WandSparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type {
  BassTranscription,
  BassTranscriptionEngine,
  BassTuning,
  DrumInstrument,
  DrumTranscription,
  TempoMap,
  TrackTranscriptionState,
  TranscriptionTrack,
} from "../domain/types";

import { useShallow } from "zustand/react/shallow";
import { useProjectStore } from "../state/projectStore";

export type StudioTab = "mixer" | "frequency" | "bass" | "drums";

interface StudioTabsProps {
  active: StudioTab;
  bassStatus: TrackTranscriptionState<BassTranscription>["status"];
  drumStatus: TrackTranscriptionState<DrumTranscription>["status"];
  onChange: (tab: StudioTab) => void;
}

export function StudioTabs({ active, bassStatus, drumStatus, onChange }: StudioTabsProps) {
  return (
    <nav className="studio-tabs" aria-label="Studio views">
      <button type="button" className={active === "mixer" ? "active" : ""} onClick={() => onChange("mixer")}>Mixer</button>
      <button type="button" className={active === "frequency" ? "active" : ""} onClick={() => onChange("frequency")}>Frequency</button>
      <button type="button" className={active === "bass" ? "active" : ""} onClick={() => onChange("bass")}>
        Bass Tab <StatusDot status={bassStatus} />
      </button>
      <button type="button" className={active === "drums" ? "active" : ""} onClick={() => onChange("drums")}>
        Drums <StatusDot status={drumStatus} />
      </button>
    </nav>
  );
}

function StatusDot({ status }: { status: "idle" | "processing" | "ready" | "error" }) {
  return status === "idle" ? null : <i className={`transcription-status-dot ${status}`} aria-label={status} />;
}

interface BassViewProps {
  state: TrackTranscriptionState<BassTranscription>;
  currentTime?: number;
  followPlayback: boolean;
  tuning: BassTuning;
  onTuningChange: (tuning: BassTuning) => void;
  engine: BassTranscriptionEngine;
  onEngineChange: (engine: BassTranscriptionEngine) => void;
  onTranscribe: () => void;
  startMarkerSeconds: number;
  onRequantize: (bpm: number, firstMeasureSeconds: number) => void;
  onSeek: (seconds: number) => void;
  onExport: (path: string, name: string, extension: "mid" | "musicxml") => void;
}

export function BassTranscriptionView({
  state,
  currentTime,
  followPlayback,
  tuning,
  onTuningChange,
  engine,
  onEngineChange,
  onTranscribe,
  startMarkerSeconds,
  onRequantize,
  onSeek,
  onExport,
}: BassViewProps) {
  const [activeId, activeMeasure] = useProjectStore(useShallow((store) => {
    const transcription = state.result?.transcription;
    const time = currentTime ?? store.currentTime;
    return [
      transcription?.events.find((event) => time >= event.detectedStartSeconds && time < event.detectedEndSeconds)?.id,
      transcription ? measureAtTime(time, transcription.tempoMap) : 1,
    ] as const;
  }));
  if (!state.result) {
    return (
      <EmptyTranscription
        track="bass"
        state={state}
        controls={
          <BassTranscriptionControls
            tuning={tuning}
            engine={engine}
            disabled={state.status === "processing"}
            onTuningChange={onTuningChange}
            onEngineChange={onEngineChange}
          />
        }
        onTranscribe={onTranscribe}
      />
    );
  }
  const { transcription, midiFile, musicXmlFile } = state.result;
  return (
    <section className="transcription-view" aria-label="Bass transcription">
      <TranscriptionHeader
        title="Bass transcription"
        subtitle={`${transcription.events.length} notes · ${tempoSummary(transcription.tempoMap)} · ${tuningLabel(transcription.tuning)} · ${bassModelLabel(transcription.modelId)}`}
        processing={state.status === "processing" ? {
          progress: state.progress,
          message: state.message,
        } : undefined}
        controls={
          <BassTranscriptionControls
            tuning={tuning}
            engine={engine}
            disabled={state.status === "processing"}
            onTuningChange={onTuningChange}
            onEngineChange={onEngineChange}
          />
        }
        onRetranscribe={onTranscribe}
        onMidi={() => onExport(midiFile, "bass.mid", "mid")}
        onMusicXml={() => onExport(musicXmlFile, "bass.musicxml", "musicxml")}
      />
      <TimingEditor
        tempoMap={transcription.tempoMap}
        startMarkerSeconds={startMarkerSeconds}
        disabled={state.status === "processing"}
        onApply={onRequantize}
      />
      <BassTab
        transcription={transcription}
        activeId={activeId}
        activeMeasure={activeMeasure}
        followPlayback={followPlayback}
        onSeek={onSeek}
      />
      <Warnings warnings={transcription.warnings} />
    </section>
  );
}

interface DrumViewProps {
  state: TrackTranscriptionState<DrumTranscription>;
  currentTime?: number;
  followPlayback: boolean;
  onTranscribe: () => void;
  startMarkerSeconds: number;
  onRequantize: (bpm: number, firstMeasureSeconds: number) => void;
  onSeek: (seconds: number) => void;
  onExport: (path: string, name: string, extension: "mid" | "musicxml") => void;
}

export function DrumTranscriptionView({
  state,
  currentTime,
  followPlayback,
  onTranscribe,
  startMarkerSeconds,
  onRequantize,
  onSeek,
  onExport,
}: DrumViewProps) {
  const [activeId, activeMeasure] = useProjectStore(useShallow((store) => {
    const transcription = state.result?.transcription;
    const time = currentTime ?? store.currentTime;
    return [
      transcription?.events.find((event) => Math.abs(time - event.detectedTimeSeconds) < 0.08)?.id,
      transcription ? measureAtTime(time, transcription.tempoMap) : 1,
    ] as const;
  }));
  if (!state.result) {
    return <EmptyTranscription track="drums" state={state} onTranscribe={onTranscribe} />;
  }
  const { transcription, midiFile, musicXmlFile } = state.result;
  return (
    <section className="transcription-view" aria-label="Drum transcription">
      <TranscriptionHeader
        title="Drum transcription"
        subtitle={`${transcription.events.length} hits · ${tempoSummary(transcription.tempoMap)} · Detailed kit`}
        processing={state.status === "processing" ? {
          progress: state.progress,
          message: state.message,
        } : undefined}
        onRetranscribe={onTranscribe}
        onMidi={() => onExport(midiFile, "drums.mid", "mid")}
        onMusicXml={() => onExport(musicXmlFile, "drums.musicxml", "musicxml")}
      />
      <TimingEditor
        tempoMap={transcription.tempoMap}
        startMarkerSeconds={startMarkerSeconds}
        disabled={state.status === "processing"}
        onApply={onRequantize}
      />
      <DrumGrid
        transcription={transcription}
        activeId={activeId}
        activeMeasure={activeMeasure}
        followPlayback={followPlayback}
        onSeek={onSeek}
      />
      <Warnings warnings={transcription.warnings} />
    </section>
  );
}

function EmptyTranscription({
  track,
  state,
  controls,
  onTranscribe,
}: {
  track: TranscriptionTrack;
  state: TrackTranscriptionState<BassTranscription> | TrackTranscriptionState<DrumTranscription>;
  controls?: ReactNode;
  onTranscribe: () => void;
}) {
  const label = track === "bass" ? "bass line" : "drum part";
  return (
    <section className="transcription-empty">
      <div className="transcription-empty-icon"><Music2 size={25} /></div>
      <h2>Transcribe the {label}</h2>
      <p>Generate editable musical events, a synchronized view, MIDI and MusicXML from the isolated {track} stem.</p>
      {controls}
      {state.status === "processing" ? (
        <div className="transcription-progress" role="status">
          <div><span style={{ width: `${state.progress * 100}%` }} /></div>
          <strong>{state.message}</strong>
          <small>{Math.round(state.progress * 100)}%</small>
        </div>
      ) : (
        <button className="primary-button transcribe-primary" type="button" onClick={onTranscribe}>
          <WandSparkles size={16} /> Transcribe {track}
        </button>
      )}
      {state.error ? <p className="transcription-error" role="alert">{state.error}</p> : null}
    </section>
  );
}

function TranscriptionHeader({
  title,
  subtitle,
  controls,
  processing,
  onRetranscribe,
  onMidi,
  onMusicXml,
}: {
  title: string;
  subtitle: string;
  controls?: ReactNode;
  processing?: { progress: number; message: string } | undefined;
  onRetranscribe: () => void;
  onMidi: () => void;
  onMusicXml: () => void;
}) {
  return (
    <header className="transcription-header">
      <div className="transcription-heading">
        <h2>{title}</h2><p>{subtitle}</p>
        {processing ? <InlineTranscriptionProgress {...processing} /> : null}
      </div>
      <div className="transcription-actions">
        {controls}
        <button type="button" className="ghost-button" disabled={Boolean(processing)} onClick={onRetranscribe}><RefreshCw size={14} /> Re-transcribe</button>
        <button type="button" className="ghost-button" disabled={Boolean(processing)} onClick={onMidi}><Download size={14} /> MIDI</button>
        <button type="button" className="primary-button" disabled={Boolean(processing)} onClick={onMusicXml}><Download size={14} /> MusicXML</button>
      </div>
    </header>
  );
}

function InlineTranscriptionProgress({ progress, message }: { progress: number; message: string }) {
  const percentage = Math.round(progress * 100);
  return (
    <div className="transcription-inline-progress" role="status" aria-live="polite">
      <div
        role="progressbar"
        aria-label={message}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percentage}
      >
        <span style={{ width: `${percentage}%` }} />
      </div>
      <small>{message} · {percentage}%</small>
    </div>
  );
}

function TimingEditor({ tempoMap, startMarkerSeconds, disabled, onApply }: {
  tempoMap: TempoMap;
  startMarkerSeconds: number;
  disabled: boolean;
  onApply: (bpm: number, firstMeasureSeconds: number) => void;
}) {
  const measureStart = firstMeasureSeconds(tempoMap);
  const [bpmValue, setBpmValue] = useState(tempoMap.bpm.toFixed(2));
  const [measureValue, setMeasureValue] = useState(measureStart.toFixed(3));
  const candidates = uniqueTempoCandidates(tempoMap);

  useEffect(() => {
    setBpmValue(tempoMap.bpm.toFixed(2));
    setMeasureValue(firstMeasureSeconds(tempoMap).toFixed(3));
  }, [tempoMap]);

  const bpm = Number(bpmValue);
  const firstMeasure = Number(measureValue);
  const valid = Number.isFinite(bpm) && bpm >= 20 && bpm <= 400
    && Number.isFinite(firstMeasure) && firstMeasure >= 0;

  return (
    <form
      className="timing-editor"
      aria-label="Transcription timing"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) onApply(bpm, firstMeasure);
      }}
    >
      <div className="timing-field">
        <label htmlFor="transcription-bpm">Tempo</label>
        <div className="timing-input-suffix">
          <input
            id="transcription-bpm"
            type="number"
            min={20}
            max={400}
            step={0.01}
            value={bpmValue}
            disabled={disabled}
            onChange={(event) => setBpmValue(event.target.value)}
          />
          <span>BPM</span>
        </div>
      </div>
      {candidates.length > 1 ? (
        <div className="tempo-candidates" aria-label="Detected tempo alternatives">
          {candidates.map((candidate) => (
            <button
              type="button"
              key={candidate}
              className={Math.abs(candidate - bpm) < 0.01 ? "is-active" : ""}
              disabled={disabled}
              onClick={() => setBpmValue(candidate.toFixed(2))}
            >{candidate.toFixed(1)}</button>
          ))}
        </div>
      ) : null}
      <div className="timing-field">
        <label htmlFor="first-measure-time">First measure</label>
        <div className="timing-input-suffix">
          <input
            id="first-measure-time"
            type="number"
            min={0}
            step={0.001}
            value={measureValue}
            disabled={disabled}
            onChange={(event) => setMeasureValue(event.target.value)}
          />
          <span>sec</span>
        </div>
      </div>
      <button
        type="button"
        className="ghost-button timing-marker-button"
        disabled={disabled}
        onClick={() => setMeasureValue(startMarkerSeconds.toFixed(3))}
      >Use marker ({startMarkerSeconds.toFixed(2)}s)</button>
      <button type="submit" className="primary-button" disabled={disabled || !valid}>Apply timing</button>
    </form>
  );
}

function BassTab({ transcription, activeId, activeMeasure, followPlayback, onSeek }: {
  transcription: BassTranscription;
  activeId: string | undefined;
  activeMeasure: number;
  followPlayback: boolean;
  onSeek: (seconds: number) => void;
}) {
  const measures = useMemo(() => bassMeasures(transcription), [transcription]);
  const strings = bassStrings(transcription.tuning);
  const scrollRef = useFollowActiveMeasure(activeMeasure, followPlayback);
  return (
    <div className="notation-scroll" ref={scrollRef}>
      <div className="measure-grid">
        {measures.map((measure) => (
          <div
            className={`tab-measure${measure.number === activeMeasure ? " is-current" : ""}`}
            data-measure={measure.number}
            key={measure.number}
          >
            <span className="measure-number">{measure.number}</span>
            {strings.map(({ stringIndex, label }) => (
              <div className="tab-string" key={stringIndex} data-label={label}>
                {measure.notes.filter((note) => note.tab.stringIndex === stringIndex).map(({ tab, event }) => (
                  <button
                    type="button"
                    className={event.id === activeId ? "active" : ""}
                    key={event.id}
                    style={{ left: `${eventPosition(tab.startBeat, measure.startBeat, measure.beats)}%` }}
                    title={`${midiName(event.midiPitch)} · ${event.detectedStartSeconds.toFixed(2)}s`}
                    onClick={() => onSeek(event.detectedStartSeconds)}
                  >{tab.fret}</button>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function DrumGrid({ transcription, activeId, activeMeasure, followPlayback, onSeek }: {
  transcription: DrumTranscription;
  activeId: string | undefined;
  activeMeasure: number;
  followPlayback: boolean;
  onSeek: (seconds: number) => void;
}) {
  const measures = useMemo(() => drumMeasures(transcription), [transcription]);
  const scrollRef = useFollowActiveMeasure(activeMeasure, followPlayback);
  return (
    <div className="notation-scroll" ref={scrollRef}>
      <div className="measure-grid drum-measure-grid">
        {measures.map((measure) => (
          <div
            className={`drum-measure${measure.number === activeMeasure ? " is-current" : ""}`}
            data-measure={measure.number}
            key={measure.number}
          >
            <span className="measure-number">{measure.number}</span>
            {DRUM_ROWS.map(({ instrument, label }) => (
              <div className="drum-row" key={instrument} data-label={label}>
                {measure.events.filter((event) => event.instrument === instrument).map((event) => (
                  <button
                    type="button"
                    className={event.id === activeId ? "active" : ""}
                    key={event.id}
                    style={{ left: `${eventPosition(event.quantizedBeat ?? 0, measure.startBeat, measure.beats)}%` }}
                    title={`${instrument} · ${event.detectedTimeSeconds.toFixed(2)}s`}
                    onClick={() => onSeek(event.detectedTimeSeconds)}
                  >{instrument.includes("hihat") || instrument === "crash" || instrument === "ride" ? "×" : "●"}</button>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  return warnings.length ? <aside className="transcription-warnings">{warnings.join(" ")}</aside> : null;
}

function BassTuningSelector({ tuning, disabled, onChange }: {
  tuning: BassTuning;
  disabled: boolean;
  onChange: (tuning: BassTuning) => void;
}) {
  return (
    <div className="bass-tuning-selector" role="group" aria-label="Bass tuning">
      <button
        type="button"
        className={tuning === "eadg" ? "is-active" : ""}
        disabled={disabled}
        aria-pressed={tuning === "eadg"}
        onClick={() => onChange("eadg")}
      >4 strings</button>
      <button
        type="button"
        className={tuning === "beadg" ? "is-active" : ""}
        disabled={disabled}
        aria-pressed={tuning === "beadg"}
        onClick={() => onChange("beadg")}
      >5 strings</button>
    </div>
  );
}

function BassTranscriptionControls({
  tuning,
  engine,
  disabled,
  onTuningChange,
  onEngineChange,
}: {
  tuning: BassTuning;
  engine: BassTranscriptionEngine;
  disabled: boolean;
  onTuningChange: (tuning: BassTuning) => void;
  onEngineChange: (engine: BassTranscriptionEngine) => void;
}) {
  return (
    <div className="bass-transcription-controls">
      <div className="bass-engine-selector" role="group" aria-label="Bass transcription engine">
        <button
          type="button"
          className={engine === "basic-pitch" ? "is-active" : ""}
          disabled={disabled}
          aria-pressed={engine === "basic-pitch"}
          onClick={() => onEngineChange("basic-pitch")}
        >Basic Pitch</button>
        <button
          type="button"
          className={engine === "torchcrepe" ? "is-active" : ""}
          disabled={disabled}
          aria-pressed={engine === "torchcrepe"}
          title="Experimental monophonic pitch tracking"
          onClick={() => onEngineChange("torchcrepe")}
        >TorchCREPE · Beta</button>
      </div>
      <BassTuningSelector tuning={tuning} disabled={disabled} onChange={onTuningChange} />
    </div>
  );
}

function bassModelLabel(modelId: string | undefined): string {
  if (modelId?.startsWith("torchcrepe")) return "TorchCREPE Beta";
  if (modelId?.startsWith("spotify-basic-pitch")) return "Basic Pitch";
  return "Bass transcription";
}

function tempoSummary(tempoMap: TempoMap): string {
  const alternatives = (tempoMap.tempoCandidates ?? []).filter(
    (candidate) => Math.abs(candidate - tempoMap.bpm) > 0.01,
  );
  const suffix = alternatives.length
    ? ` · alternatives ${alternatives.map((candidate) => candidate.toFixed(1)).join("/")}`
    : "";
  return `${tempoMap.bpm.toFixed(1)} BPM${suffix}`;
}

function firstMeasureSeconds(tempoMap: TempoMap): number {
  return tempoMap.beats.find((beat) => beat.beatIndex === 0)?.timeSeconds
    ?? tempoMap.beats[0]?.timeSeconds
    ?? 0;
}

function uniqueTempoCandidates(tempoMap: TempoMap): number[] {
  return [...new Set([tempoMap.bpm, ...(tempoMap.tempoCandidates ?? [])])]
    .filter((candidate) => Number.isFinite(candidate) && candidate >= 20 && candidate <= 400)
    .sort((left, right) => left - right);
}

function useFollowActiveMeasure(activeMeasure: number, enabled: boolean) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) return;
    const container = scrollRef.current;
    const target = container?.querySelector<HTMLElement>(`[data-measure="${activeMeasure}"]`);
    if (!container || !target) return;

    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const edgePadding = 24;
    const isVisible =
      targetRect.top >= containerRect.top + edgePadding &&
      targetRect.bottom <= containerRect.bottom - edgePadding;
    if (isVisible) return;

    const centeredTop =
      container.scrollTop +
      targetRect.top -
      containerRect.top -
      (container.clientHeight - targetRect.height) / 2;
    container.scrollTo({ top: Math.max(0, centeredTop) });
  }, [activeMeasure, enabled]);

  return scrollRef;
}

const DRUM_ROWS: { instrument: DrumInstrument; label: string }[] = [
  { instrument: "crash", label: "CY" },
  { instrument: "ride", label: "RD" },
  { instrument: "open_hihat", label: "HO" },
  { instrument: "closed_hihat", label: "HH" },
  { instrument: "high_tom", label: "TH" },
  { instrument: "mid_tom", label: "TM" },
  { instrument: "low_tom", label: "TL" },
  { instrument: "snare", label: "SN" },
  { instrument: "kick", label: "BD" },
  { instrument: "other", label: "OT" },
];

const PITCH_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];

function bassStrings(tuning: number[]) {
  return tuning
    .map((midiPitch, stringIndex) => ({ stringIndex, label: PITCH_NAMES[midiPitch % 12] }))
    .reverse();
}

function tuningLabel(tuning: number[]) {
  return bassStrings(tuning).reverse().map(({ label }) => label).join("");
}

function bassMeasures(transcription: BassTranscription) {
  const beats = measureLength(transcription.tempoMap.timeSignature);
  const events = new Map(transcription.events.map((event) => [event.id, event]));
  const earliestBeat = Math.min(0, ...transcription.tab.map((note) => note.startBeat));
  const count = Math.max(1, Math.ceil(Math.max(0, ...transcription.tab.map((note) => note.startBeat + note.durationBeats)) / beats));
  const regular = Array.from({ length: count }, (_, index) => {
    const startBeat = index * beats;
    return {
      number: index + 1,
      startBeat,
      beats,
      notes: transcription.tab.flatMap((tab) => {
        const event = events.get(tab.noteEventId);
        return event && tab.startBeat >= startBeat && tab.startBeat < startBeat + beats ? [{ tab, event }] : [];
      }),
    };
  });
  if (earliestBeat >= 0) return regular;
  return [{
    number: 0,
    startBeat: earliestBeat,
    beats: -earliestBeat,
    notes: transcription.tab.flatMap((tab) => {
      const event = events.get(tab.noteEventId);
      return event && tab.startBeat < 0 ? [{ tab, event }] : [];
    }),
  }, ...regular];
}

function drumMeasures(transcription: DrumTranscription) {
  const beats = measureLength(transcription.tempoMap.timeSignature);
  const earliestBeat = Math.min(0, ...transcription.events.map((event) => event.quantizedBeat ?? 0));
  const lastBeat = Math.max(0, ...transcription.events.map((event) => event.quantizedBeat ?? 0));
  const count = Math.max(1, Math.floor(lastBeat / beats) + 1);
  const regular = Array.from({ length: count }, (_, index) => {
    const startBeat = index * beats;
    return {
      number: index + 1,
      startBeat,
      beats,
      events: transcription.events.filter((event) => {
        const beat = event.quantizedBeat ?? 0;
        return beat >= startBeat && beat < startBeat + beats;
      }),
    };
  });
  if (earliestBeat >= 0) return regular;
  return [{
    number: 0,
    startBeat: earliestBeat,
    beats: -earliestBeat,
    events: transcription.events.filter((event) => (event.quantizedBeat ?? 0) < 0),
  }, ...regular];
}

function measureLength(signature: { numerator: number; denominator: number }) {
  return (signature.numerator * 4) / signature.denominator;
}

export function measureAtTime(timeSeconds: number, tempoMap: TempoMap): number {
  const beatsPerMeasure = measureLength(tempoMap.timeSignature);
  const firstBeat = tempoMap.beats[0];
  if (!firstBeat) return 1;
  if (timeSeconds < firstBeat.timeSeconds) return 0;
  if (timeSeconds === firstBeat.timeSeconds) return 1;

  let low = 0;
  let high = tempoMap.beats.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if ((tempoMap.beats[middle]?.timeSeconds ?? Number.POSITIVE_INFINITY) <= timeSeconds) low = middle;
    else high = middle - 1;
  }

  const lastKnownBeat = tempoMap.beats[low];
  if (!lastKnownBeat) return 1;
  const elapsedAfterBeat = Math.max(0, timeSeconds - lastKnownBeat.timeSeconds);
  const estimatedBeat = lastKnownBeat.beatIndex + elapsedAfterBeat * tempoMap.bpm / 60;
  return Math.max(1, Math.floor(estimatedBeat / beatsPerMeasure) + 1);
}

function eventPosition(beat: number, measureStart: number, measureBeats: number) {
  return 2 + ((beat - measureStart) / measureBeats) * 96;
}

function midiName(pitch: number): string {
  return `${PITCH_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}
