import { STEM_NAMES, type StemName, type StemState } from "./types";

export const DEFAULT_TRACK: StemState = { volume: 0.8, muted: false, solo: false };

export function createDefaultTracks(): Record<StemName, StemState> {
  return Object.fromEntries(
    STEM_NAMES.map((name) => [name, { ...DEFAULT_TRACK }]),
  ) as Record<StemName, StemState>;
}

export function calculateEffectiveGains(
  tracks: Record<StemName, StemState>,
): Record<StemName, number> {
  const hasSolo = STEM_NAMES.some((name) => tracks[name].solo);

  return Object.fromEntries(
    STEM_NAMES.map((name) => {
      const track = tracks[name];
      const audible = !track.muted && (!hasSolo || track.solo);
      return [name, audible ? clampVolume(track.volume) : 0];
    }),
  ) as Record<StemName, number>;
}

export function clampVolume(volume: number): number {
  return Math.min(1, Math.max(0, volume));
}

