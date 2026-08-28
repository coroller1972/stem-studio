import { describe, expect, it } from "vitest";
import { calculateSpectrogram, midiFrequency, midiNoteName, spectrogramRange } from "./spectrogram";

describe("spectrogram", () => {
  it("uses scientific pitch notation", () => {
    expect(midiNoteName(21)).toBe("A0");
    expect(midiNoteName(24)).toBe("C1");
    expect(midiNoteName(59)).toBe("B3");
    expect(midiFrequency(69)).toBe(440);
    expect(spectrogramRange("bass")).toEqual({ minMidi: 21, maxMidi: 84 });
    expect(spectrogramRange("vocals")).toEqual({ minMidi: 24, maxMidi: 108 });
  });

  it("places a 110 Hz sine wave on A2", () => {
    const sampleRate = 44_100;
    const samples = Float32Array.from({ length: 12_000 }, (_, index) =>
      Math.sin((2 * Math.PI * 110 * index) / sampleRate),
    );
    const result = calculateSpectrogram(samples, sampleRate, 3, 21, 72, 8_192);
    const middleColumn = 1;
    let strongestRow = 0;
    for (let row = 1; row < result.height; row += 1) {
      if (result.values[middleColumn * result.height + row]! > result.values[middleColumn * result.height + strongestRow]!) {
        strongestRow = row;
      }
    }
    expect(result.maxMidi - strongestRow).toBe(45);
  });
});
