export interface MetronomeSettings {
  countInBars: number;
  /** Clicks while the song plays; the count-in clicks regardless. */
  songClicks: boolean;
  volume: number;
}

export const DEFAULT_METRONOME_SETTINGS: MetronomeSettings = { countInBars: 1, songClicks: false, volume: 0.8 };

export const COUNT_IN_CHOICES = [
  { bars: 0, label: "Off" },
  { bars: 1, label: "1 bar" },
  { bars: 2, label: "2 bars" },
] as const;

/** Remembered per device; private browsing or blocked storage falls back to the defaults. */
export function loadMetronomeSettings(
  storageKey: string,
  defaults: MetronomeSettings = DEFAULT_METRONOME_SETTINGS,
): MetronomeSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null") as Partial<MetronomeSettings> | null;
    if (!saved || typeof saved !== "object") return defaults;
    return {
      countInBars: COUNT_IN_CHOICES.some((choice) => choice.bars === saved.countInBars)
        ? saved.countInBars!
        : defaults.countInBars,
      songClicks: typeof saved.songClicks === "boolean" ? saved.songClicks : defaults.songClicks,
      volume: typeof saved.volume === "number" && saved.volume >= 0 && saved.volume <= 1
        ? saved.volume
        : defaults.volume,
    };
  } catch {
    return defaults;
  }
}

export function saveMetronomeSettings(storageKey: string, settings: MetronomeSettings): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(settings));
  } catch {
    // Settings simply reset next time.
  }
}
