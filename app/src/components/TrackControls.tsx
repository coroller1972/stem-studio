import { WandSparkles } from "lucide-react";
import type { StemName, StemState, TranscriptionStatus } from "../domain/types";

const LABELS: Record<StemName, string> = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  other: "Other",
};

interface TrackControlsProps {
  name: StemName;
  track: StemState;
  onChange: (patch: Partial<StemState>) => void;
  transcriptionStatus?: TranscriptionStatus;
  onTranscribe?: () => void;
}

export function TrackControls({ name, track, onChange, transcriptionStatus, onTranscribe }: TrackControlsProps) {
  const percent = Math.round(track.volume * 100);
  return (
    <div className="track-controls">
      <div className="track-title-row">
        <span className={`track-dot track-dot-${name}`} />
        <h3>{LABELS[name]}</h3>
      </div>
      <div className="track-settings">
        <div className="toggle-pair">
          <button
            type="button"
            className={track.muted ? "active mute-active" : ""}
            aria-pressed={track.muted}
            aria-label={`Mute ${LABELS[name]}`}
            onClick={() => onChange({ muted: !track.muted })}
          >
            M
          </button>
          <button
            type="button"
            className={track.solo ? "active solo-active" : ""}
            aria-pressed={track.solo}
            aria-label={`Solo ${LABELS[name]}`}
            onClick={() => onChange({ solo: !track.solo })}
          >
            S
          </button>
        </div>
        <label className="volume-control">
          <span className="sr-only">{LABELS[name]} volume</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={track.volume}
            onChange={(event) => onChange({ volume: Number(event.currentTarget.value) })}
            style={{ "--range-progress": `${percent}%` } as React.CSSProperties}
          />
          <output>{percent}%</output>
        </label>
      </div>
      {onTranscribe ? (
        <button
          className="track-transcribe-button"
          type="button"
          disabled={transcriptionStatus === "processing"}
          onClick={onTranscribe}
        >
          <WandSparkles size={12} />
          {transcriptionStatus === "processing" ? "Transcribing…" : transcriptionStatus === "ready" ? "Re-transcribe" : "Transcribe"}
        </button>
      ) : null}
    </div>
  );
}
