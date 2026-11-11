import { COUNT_IN_CHOICES, type MetronomeSettings } from "../domain/metronomeSettings";

export const PLAYER_METRONOME_STORAGE_KEY = "stem-player.metronome";

/** Always on screen while a song with a tempo is loaded: set it up just before playing. */
export function MetronomePanel({ settings, onChange }: {
  settings: MetronomeSettings;
  onChange: (settings: MetronomeSettings) => void;
}) {
  return (
    <section className="metronome-panel" aria-label="Metronome">
      <div className="metronome-row">
        <span>Count-in</span>
        <div className="metronome-choices" role="group" aria-label="Count-in">
          {COUNT_IN_CHOICES.map((choice) => (
            <button
              key={choice.bars}
              type="button"
              aria-pressed={settings.countInBars === choice.bars}
              onClick={() => onChange({ ...settings, countInBars: choice.bars })}
            >
              {choice.label}
            </button>
          ))}
        </div>
      </div>
      <div className="metronome-row">
        <span>Click</span>
        <div className="metronome-choices" role="group" aria-label="Click during song">
          <button type="button" aria-pressed={!settings.songClicks} onClick={() => onChange({ ...settings, songClicks: false })}>
            Off
          </button>
          <button type="button" aria-pressed={settings.songClicks} onClick={() => onChange({ ...settings, songClicks: true })}>
            On
          </button>
        </div>
        <label className="metronome-volume volume-control">
          <span className="sr-only">Click volume</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={settings.volume}
            aria-label="Click volume"
            style={{ "--range-progress": `${settings.volume * 100}%` } as React.CSSProperties}
            onInput={(event) => onChange({ ...settings, volume: Number(event.currentTarget.value) })}
          />
        </label>
      </div>
    </section>
  );
}
