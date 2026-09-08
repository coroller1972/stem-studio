import { Flag, Pause, Play, RotateCcw, SkipBack, Volume1, Volume2, VolumeX } from "lucide-react";
import type { TransportStatus } from "../domain/types";
import { formatTime } from "../domain/transport";

import { useProjectStore } from "../state/projectStore";

interface TransportProps {
  status: TransportStatus;
  duration: number;
  marker: number;
  masterVolume: number;
  onToggle: () => void;
  onReturnToMarker: () => void;
  onPlayFromMarker: () => void;
  onSetMarker: () => void;
  onMasterVolumeChange: (volume: number) => void;
}

export function Transport({
  status,
  duration,
  marker,
  masterVolume,
  onToggle,
  onReturnToMarker,
  onPlayFromMarker,
  onSetMarker,
  onMasterVolumeChange,
}: TransportProps) {
  const isPlaying = status === "playing";
  const MasterVolumeIcon = masterVolume === 0 ? VolumeX : masterVolume < 0.5 ? Volume1 : Volume2;
  return (
    <footer className="transport">
      <div className="transport-controls">
        <button type="button" onClick={onReturnToMarker} title="Return to start marker">
          <SkipBack size={17} fill="currentColor" />
          <span className="sr-only">Return to start marker</span>
        </button>
        <button type="button" onClick={onPlayFromMarker} title="Play from start marker">
          <RotateCcw size={17} />
          <span className="sr-only">Play from start marker</span>
        </button>
        <button
          type="button"
          className="play-button"
          onClick={onToggle}
          title={isPlaying ? "Pause (Space)" : "Play (Space)"}
        >
          {isPlaying ? <Pause size={21} fill="currentColor" /> : <Play size={21} fill="currentColor" />}
          <span className="sr-only">{isPlaying ? "Pause" : "Play"}</span>
        </button>
      </div>
      <TransportClock duration={duration} />
      <button className="marker-readout" type="button" onClick={onSetMarker} title="Set marker to playhead">
        <Flag size={13} />
        <span>START</span>
        <strong>{formatTime(marker)}</strong>
      </button>
      <label className="master-volume">
        <MasterVolumeIcon size={15} aria-hidden="true" />
        <span className="sr-only">Master volume</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={masterVolume}
          aria-label="Master volume"
          style={{ "--range-progress": `${masterVolume * 100}%` } as React.CSSProperties}
          onInput={(event) => onMasterVolumeChange(Number(event.currentTarget.value))}
        />
        <output>{Math.round(masterVolume * 100)}%</output>
      </label>
    </footer>
  );
}

function TransportClock({ duration }: { duration: number }) {
  const time = useProjectStore((state) => formatTime(state.currentTime));
  return <div className="transport-clock" aria-live="off"><strong>{time}</strong><span>/</span><span>{formatTime(duration)}</span></div>;
}
