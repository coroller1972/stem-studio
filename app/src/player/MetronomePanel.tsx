export interface MetronomeSettings {
  countInBars: number;
  songClicks: boolean;
  volume: number;
}

export const DEFAULT_METRONOME_SETTINGS: MetronomeSettings = { countInBars: 1, songClicks: false, volume: 0.8 };
const COUNT_IN_CHOICES = [
  { bars: 0, label: "Off" },
  { bars: 1, label: "1 bar" },
  { bars: 2, label: "2 bars" },
];
const STORAGE_KEY = "stem-player.metronome";

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

/** Remembered per phone; private browsing or blocked storage falls back to the defaults. */
export function loadMetronomeSettings(): MetronomeSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<MetronomeSettings> | null;
    if (!saved) return DEFAULT_METRONOME_SETTINGS;
    return {
      countInBars: COUNT_IN_CHOICES.some((choice) => choice.bars === saved.countInBars)
        ? saved.countInBars!
        : DEFAULT_METRONOME_SETTINGS.countInBars,
      songClicks: saved.songClicks === true,
      volume: typeof saved.volume === "number" && saved.volume >= 0 && saved.volume <= 1
        ? saved.volume
        : DEFAULT_METRONOME_SETTINGS.volume,
    };
  } catch {
    return DEFAULT_METRONOME_SETTINGS;
  }
}

export function saveMetronomeSettings(settings: MetronomeSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Settings simply reset next time.
  }
}
