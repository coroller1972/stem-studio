import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_METRONOME_SETTINGS, loadMetronomeSettings, saveMetronomeSettings } from "./metronomeSettings";

const KEY = "test.metronome";

describe("metronome settings", () => {
  afterEach(() => localStorage.clear());

  it("round-trips through local storage", () => {
    saveMetronomeSettings(KEY, { countInBars: 2, songClicks: true, volume: 0.4 });
    expect(loadMetronomeSettings(KEY)).toEqual({ countInBars: 2, songClicks: true, volume: 0.4 });
  });

  it("falls back to each device's defaults for missing or damaged values", () => {
    const desktop = { countInBars: 0, songClicks: false, volume: 0.8 };
    expect(loadMetronomeSettings(KEY)).toEqual(DEFAULT_METRONOME_SETTINGS);
    expect(loadMetronomeSettings(KEY, desktop)).toEqual(desktop);
    localStorage.setItem(KEY, JSON.stringify({ countInBars: 7, songClicks: "yes", volume: 3 }));
    expect(loadMetronomeSettings(KEY, desktop)).toEqual(desktop);
    localStorage.setItem(KEY, "{not json");
    expect(loadMetronomeSettings(KEY, desktop)).toEqual(desktop);
  });
});
