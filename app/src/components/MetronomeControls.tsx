import { useEffect, useRef, useState } from "react";
import { ChevronUp, Crosshair, Timer } from "lucide-react";
import { COUNT_IN_CHOICES, type MetronomeSettings } from "../domain/metronomeSettings";
import {
  addTap,
  MAX_BPM,
  MIN_BPM,
  tapTempo,
  type ManualTempoInput,
  type TempoChoice,
  type TempoSourceId,
} from "../domain/metronomeTempo";
import { formatTime } from "../domain/transport";

const SOURCE_LABELS: Record<TempoSourceId, string> = { drums: "Drums", bass: "Bass", manual: "Manual" };
const SOURCE_ORDER: readonly TempoSourceId[] = ["drums", "bass", "manual"];
const BEATS_PER_BAR_CHOICES = [2, 3, 4, 5, 6, 7, 9, 12];

interface MetronomeControlsProps {
  settings: MetronomeSettings;
  onSettingsChange: (settings: MetronomeSettings) => void;
  choice: TempoChoice;
  /** The detected or manual tempo actually followed, once the beats are smoothed. */
  bpm: number | null;
  onSourceChange: (source: TempoSourceId) => void;
  manual: ManualTempoInput;
  onManualChange: (manual: ManualTempoInput) => void;
  /** Song time while playing, for tapping along and placing bar 1; null when stopped. */
  playingTime: () => number | null;
  /** The playhead, playing or not. */
  playhead: () => number;
}

/** Click on/off in the transport bar, with the tempo, count-in and volume in a popover. */
export function MetronomeControls({
  settings,
  onSettingsChange,
  choice,
  bpm,
  onSourceChange,
  manual,
  onManualChange,
  playingTime,
  playhead,
}: MetronomeControlsProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const taps = useRef<number[]>([]);
  const [bpmDraft, setBpmDraft] = useState(manual.bpm === null ? "" : String(manual.bpm));

  useEffect(() => setBpmDraft(manual.bpm === null ? "" : String(manual.bpm)), [manual.bpm]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const commitBpm = (text: string) => {
    const value = Number(text.replace(",", "."));
    if (text.trim() === "") onManualChange({ ...manual, bpm: null });
    else if (Number.isFinite(value) && value >= MIN_BPM && value <= MAX_BPM) onManualChange({ ...manual, bpm: value });
    else setBpmDraft(manual.bpm === null ? "" : String(manual.bpm));
  };

  const tap = () => {
    const songTime = playingTime();
    // While playing, taps are placed in the song so the first one marks bar 1.
    const at = songTime ?? performance.now() / 1000;
    taps.current = addTap(taps.current, at);
    const tapped = tapTempo(taps.current);
    if (!tapped) return;
    onManualChange({
      ...manual,
      bpm: tapped.bpm,
      downbeatSeconds: songTime === null ? manual.downbeatSeconds : tapped.downbeatSeconds,
    });
  };

  const tempo = choice.tempo;
  const countInLabel = settings.countInBars > 0 ? `${settings.countInBars}-bar count-in` : "No count-in";
  return (
    <div className="metronome-control" ref={rootRef}>
      <button
        type="button"
        className="metronome-toggle"
        aria-pressed={settings.songClicks}
        disabled={!tempo}
        title={tempo ? (settings.songClicks ? "Turn the click off" : "Turn the click on") : "Set a tempo first"}
        onClick={() => onSettingsChange({ ...settings, songClicks: !settings.songClicks })}
      >
        <Timer size={16} />
        <span className="sr-only">Metronome click</span>
      </button>
      <button
        type="button"
        className="metronome-readout"
        aria-expanded={open}
        aria-haspopup="dialog"
        title={tempo ? `Metronome: ${tempo.source}, ${countInLabel.toLowerCase()}` : "Metronome settings"}
        onClick={() => setOpen((value) => !value)}
      >
        <strong>{bpm === null ? "—" : formatBpm(bpm)}</strong>
        <span>BPM</span>
        {tempo ? <em>{tempo.beatsPerBar}/bar</em> : null}
        {tempo && settings.countInBars > 0 ? <em className="metronome-count-in">+{settings.countInBars}</em> : null}
        <ChevronUp size={13} aria-hidden="true" />
      </button>
      {open ? (
        <div className="metronome-popover" role="dialog" aria-label="Metronome settings">
          <div className="metronome-field">
            <span>Tempo</span>
            <div className="metronome-segments" role="group" aria-label="Tempo source">
              {SOURCE_ORDER.map((source) => {
                const available = choice.available.includes(source);
                return (
                  <button
                    key={source}
                    type="button"
                    aria-pressed={choice.source === source}
                    disabled={!available}
                    title={available ? undefined : `Transcribe the ${source} to follow its beats`}
                    onClick={() => onSourceChange(source)}
                  >
                    {SOURCE_LABELS[source]}
                  </button>
                );
              })}
            </div>
          </div>
          {choice.source === "manual" ? (
            <>
              <div className="metronome-field">
                <span>BPM</span>
                <div className="metronome-inline">
                  <input
                    className="metronome-bpm-input"
                    type="text"
                    inputMode="decimal"
                    placeholder="120"
                    aria-label="Tempo in beats per minute"
                    value={bpmDraft}
                    onChange={(event) => setBpmDraft(event.currentTarget.value)}
                    onBlur={(event) => commitBpm(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitBpm(event.currentTarget.value);
                    }}
                  />
                  <button
                    type="button"
                    className="metronome-small-button"
                    title="Tap along on the beats; while playing, start on a bar's first beat"
                    onClick={tap}
                  >
                    Tap
                  </button>
                  <select
                    aria-label="Beats per bar"
                    value={manual.beatsPerBar}
                    onChange={(event) => onManualChange({ ...manual, beatsPerBar: Number(event.currentTarget.value) })}
                  >
                    {BEATS_PER_BAR_CHOICES.map((beats) => (
                      <option key={beats} value={beats}>{beats} beats/bar</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="metronome-field">
                <span>Bar 1</span>
                <div className="metronome-inline">
                  <output className="metronome-downbeat">{formatTime(manual.downbeatSeconds)}</output>
                  <button
                    type="button"
                    className="metronome-small-button"
                    title="Place a bar's first beat at the playhead"
                    onClick={() => onManualChange({ ...manual, downbeatSeconds: playhead() })}
                  >
                    <Crosshair size={13} aria-hidden="true" /> At playhead
                  </button>
                </div>
              </div>
            </>
          ) : tempo ? (
            <p className="metronome-note">
              Follows the beats of the {tempo.source}, {tempo.beatsPerBar} per bar. Correct its tempo in the{" "}
              {SOURCE_LABELS[choice.source]} tab.
            </p>
          ) : null}
          <div className="metronome-field">
            <span>Count-in</span>
            <div className="metronome-segments" role="group" aria-label="Count-in">
              {COUNT_IN_CHOICES.map((option) => (
                <button
                  key={option.bars}
                  type="button"
                  aria-pressed={settings.countInBars === option.bars}
                  onClick={() => onSettingsChange({ ...settings, countInBars: option.bars })}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="metronome-field">
            <span>Click</span>
            <div className="metronome-inline">
              <div className="metronome-segments" role="group" aria-label="Click during song">
                <button
                  type="button"
                  aria-pressed={!settings.songClicks}
                  onClick={() => onSettingsChange({ ...settings, songClicks: false })}
                >
                  Off
                </button>
                <button
                  type="button"
                  aria-pressed={settings.songClicks}
                  onClick={() => onSettingsChange({ ...settings, songClicks: true })}
                >
                  On
                </button>
              </div>
              <input
                className="metronome-volume-input"
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={settings.volume}
                aria-label="Click volume"
                style={{ "--range-progress": `${settings.volume * 100}%` } as React.CSSProperties}
                onInput={(event) => onSettingsChange({ ...settings, volume: Number(event.currentTarget.value) })}
              />
            </div>
          </div>
          {!tempo ? (
            <p className="metronome-note">
              No transcription tempo yet: type or tap the BPM, or transcribe the drums or bass.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function formatBpm(bpm: number): string {
  return Math.abs(bpm - Math.round(bpm)) < 0.05 ? String(Math.round(bpm)) : bpm.toFixed(1);
}
