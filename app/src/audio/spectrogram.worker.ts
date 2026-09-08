import { DEFAULT_FFT_SIZE, SPECTROGRAM_BATCH_COLUMNS, SpectrogramAccumulator } from "./spectrogram";

type SpectrogramRequest =
  | { type: "start"; sampleRate: number; width: number; minMidi: number; maxMidi: number }
  | { type: "frames"; samples: ArrayBuffer };

let accumulator: SpectrogramAccumulator | null = null;
let column = 0;

self.onmessage = (event: MessageEvent<SpectrogramRequest>) => {
  try {
    const request = event.data;
    if (request.type === "start") {
      accumulator = new SpectrogramAccumulator(request.sampleRate, request.width, request.minMidi, request.maxMidi);
      column = 0;
    } else {
      if (!accumulator) throw new Error("Frequency analysis has not started.");
      const frames = new Float32Array(request.samples);
      for (let offset = 0; offset < frames.length; offset += DEFAULT_FFT_SIZE) {
        accumulator.addFrame(column++, frames.subarray(offset, offset + DEFAULT_FFT_SIZE));
      }
    }
    if (!accumulator) return;
    if (column < accumulator.width) {
      self.postMessage({ type: "frames-needed", column, count: Math.min(SPECTROGRAM_BATCH_COLUMNS, accumulator.width - column) });
    } else {
      const result = accumulator.finish();
      accumulator = null;
      self.postMessage({ type: "result", result }, { transfer: [result.values.buffer] });
    }
  } catch (error) {
    accumulator = null;
    self.postMessage({ type: "error", message: error instanceof Error ? error.message : String(error) });
  }
};

export {};
