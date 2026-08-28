import { describe, expect, it } from "vitest";
import { centerScrollLeft, followScrollLeft, nextSpectrumZoom } from "../domain/frequencyZoom";

describe("frequency view zoom", () => {
  it("moves through the supported zoom levels and clamps at the ends", () => {
    expect(nextSpectrumZoom(1, 1)).toBe(2);
    expect(nextSpectrumZoom(2, 1)).toBe(4);
    expect(nextSpectrumZoom(8, 1)).toBe(8);
    expect(nextSpectrumZoom(4, -1)).toBe(2);
    expect(nextSpectrumZoom(1, -1)).toBe(1);
  });

  it("centers the current playhead after changing zoom", () => {
    expect(centerScrollLeft(1_000, 4_000, 0.5)).toBe(1_500);
    expect(centerScrollLeft(1_000, 4_000, 0)).toBe(0);
    expect(centerScrollLeft(1_000, 4_000, 1)).toBe(3_000);
  });

  it("scrolls only when playback leaves the safe visible area", () => {
    expect(followScrollLeft(1_000, 1_000, 4_000, 0.4)).toBe(1_000);
    expect(followScrollLeft(1_000, 1_000, 4_000, 0.7)).toBe(2_450);
    expect(followScrollLeft(1_000, 1_000, 4_000, 0.1)).toBe(50);
  });
});
