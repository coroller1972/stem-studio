import { calculateSpectrogram } from "./spectrogram";

interface SpectrogramRequest {
  samples: ArrayBuffer;
  sampleRate: number;
  width: number;
  minMidi: number;
  maxMidi: number;
}

self.onmessage = (event: MessageEvent<SpectrogramRequest>) => {
  try {
    const result = calculateSpectrogram(
      new Float32Array(event.data.samples),
      event.data.sampleRate,
      event.data.width,
      event.data.minMidi,
      event.data.maxMidi,
    );
    self.postMessage({ type: "result", result }, { transfer: [result.values.buffer] });
  } catch (error) {
    self.postMessage({
      type: "error",
      message: error instanceof Error ? error.message : String(error),
    });
  }
};

export {};
