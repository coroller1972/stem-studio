import { useMemo, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { Flag } from "lucide-react";
import { STEM_NAMES, type ProjectTranscriptions, type StemName, type StemState, type TranscriptionTrack } from "../domain/types";
import { formatTime } from "../domain/transport";
import { TrackControls } from "./TrackControls";

interface TimelineProps {
  duration: number;
  currentTime: number;
  startMarkerSeconds: number;
  tracks: Record<StemName, StemState>;
  waveforms: Partial<Record<StemName, Float32Array>>;
  onTrackChange: (name: StemName, patch: Partial<StemState>) => void;
  onSeek: (seconds: number) => void;
  onMarkerChange: (seconds: number) => void;
  transcriptions: ProjectTranscriptions;
  onTranscribe: (track: TranscriptionTrack) => void;
}

export function Timeline({
  duration,
  currentTime,
  startMarkerSeconds,
  tracks,
  waveforms,
  onTrackChange,
  onSeek,
  onMarkerChange,
  transcriptions,
  onTranscribe,
}: TimelineProps) {
  const laneRef = useRef<HTMLDivElement>(null);
  const draggingMarker = useRef(false);
  const ticks = useMemo(() => createTicks(duration), [duration]);
  const playheadPercent = toPercent(currentTime, duration);
  const markerPercent = toPercent(startMarkerSeconds, duration);

  const secondsFromClientX = (clientX: number): number => {
    const rect = laneRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * duration;
  };

  const handleLanePointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    onSeek(secondsFromClientX(event.clientX));
  };

  const handleMarkerPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    draggingMarker.current = true;
    const move = (moveEvent: PointerEvent) => {
      if (draggingMarker.current) onMarkerChange(secondsFromClientX(moveEvent.clientX));
    };
    const finish = () => {
      draggingMarker.current = false;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
  };

  return (
    <section className="timeline" aria-label="Stem timeline">
      <div className="time-ruler-label">TIME</div>
      <div className="time-ruler" ref={laneRef}>
        {ticks.map((tick) => (
          <span key={tick.seconds} style={{ left: `${tick.percent}%` }}>
            {formatRulerTime(tick.seconds)}
          </span>
        ))}
      </div>
      <div className="tracks-region">
        <div className="tracks-grid">
          {STEM_NAMES.map((name) => (
            <div className="track-row" key={name}>
              <TrackControls
                name={name}
                track={tracks[name]}
                onChange={(patch) => onTrackChange(name, patch)}
                {...(name === "bass" || name === "drums"
                  ? {
                      transcriptionStatus: transcriptions[name].status,
                      onTranscribe: () => onTranscribe(name),
                    }
                  : {})}
              />
              <Waveform name={name} peaks={waveforms[name]} ticks={ticks} />
            </div>
          ))}
        </div>
        <div
          className="timeline-interaction"
          onPointerDown={handleLanePointerDown}
          title="Click to seek"
        >
          <div className="playhead" style={{ left: `${playheadPercent}%` }}>
            <span />
          </div>
          <button
            type="button"
            className="start-marker"
            style={{ left: `${markerPercent}%` }}
            onPointerDown={handleMarkerPointerDown}
            onKeyDown={(event) => {
              if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
              event.preventDefault();
              const direction = event.key === "ArrowLeft" ? -1 : 1;
              onMarkerChange(startMarkerSeconds + direction * (event.shiftKey ? 5 : 1));
            }}
            aria-label={`Start marker at ${formatTime(startMarkerSeconds)}`}
            title="Drag start marker"
          >
            <Flag size={12} />
          </button>
        </div>
      </div>
    </section>
  );
}

function Waveform({
  name,
  peaks,
  ticks,
}: {
  name: StemName;
  peaks: Float32Array | undefined;
  ticks: ReturnType<typeof createTicks>;
}) {
  const path = useMemo(() => createWaveformPath(peaks), [peaks]);
  return (
    <div className={`waveform waveform-${name}`}>
      {ticks.map((tick) => (
        <i key={tick.seconds} style={{ left: `${tick.percent}%` }} />
      ))}
      <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
        <path d={path} />
      </svg>
    </div>
  );
}

function createWaveformPath(peaks?: Float32Array): string {
  if (!peaks?.length) return "M0 50 L1000 50";
  const points: string[] = ["M0 50"];
  const max = peaks.reduce((value, peak) => Math.max(value, peak), 0.001);
  for (let index = 0; index < peaks.length; index += 1) {
    const x = (index / Math.max(1, peaks.length - 1)) * 1000;
    const amplitude = ((peaks[index] ?? 0) / max) * 43;
    points.push(`L${x.toFixed(2)} ${(50 - amplitude).toFixed(2)}`);
  }
  for (let index = peaks.length - 1; index >= 0; index -= 1) {
    const x = (index / Math.max(1, peaks.length - 1)) * 1000;
    const amplitude = ((peaks[index] ?? 0) / max) * 43;
    points.push(`L${x.toFixed(2)} ${(50 + amplitude).toFixed(2)}`);
  }
  return `${points.join(" ")} Z`;
}

function createTicks(duration: number) {
  const desiredTicks = 8;
  const roughStep = duration / desiredTicks;
  const steps = [5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((candidate) => candidate >= roughStep) ?? 600;
  const ticks = [];
  for (let seconds = 0; seconds <= duration; seconds += step) {
    ticks.push({ seconds, percent: toPercent(seconds, duration) });
  }
  return ticks;
}

function toPercent(seconds: number, duration: number): number {
  return duration > 0 ? (Math.min(duration, Math.max(0, seconds)) / duration) * 100 : 0;
}

function formatRulerTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}
