import type { SpectralStemName, SpectrogramData } from "../domain/types";

export const DEFAULT_FFT_SIZE = 8_192;
export const SPECTROGRAM_BATCH_COLUMNS = 32;
const DECIBEL_RANGE = 72;
const SILENCE_DB = -240;

export function spectrogramRange(stem: SpectralStemName): { minMidi: number; maxMidi: number } {
  if (stem === "bass") return { minMidi: 21, maxMidi: 84 };
  if (stem === "vocals") return { minMidi: 24, maxMidi: 108 };
  return { minMidi: 21, maxMidi: 108 };
}

export function midiFrequency(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

export function midiNoteName(midi: number): string {
  const names = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
  const rounded = Math.round(midi);
  return `${names[((rounded % 12) + 12) % 12]}${Math.floor(rounded / 12) - 1}`;
}

export function calculateSpectrogram(
  samples: Float32Array,
  sampleRate: number,
  width: number,
  minMidi: number,
  maxMidi: number,
  fftSize = DEFAULT_FFT_SIZE,
): SpectrogramData {
  const accumulator = new SpectrogramAccumulator(sampleRate, width, minMidi, maxMidi, fftSize);
  const frame = new Float32Array(fftSize);
  for (let column = 0; column < accumulator.width; column += 1) {
    const start = spectrogramFrameStart(samples.length, column, accumulator.width, fftSize);
    for (let index = 0; index < fftSize; index += 1) frame[index] = samples[start + index] ?? 0;
    accumulator.addFrame(column, frame);
  }
  return accumulator.finish();
}

export function spectrogramFrameStart(length: number, column: number, width: number, fftSize = DEFAULT_FFT_SIZE): number {
  const center = width === 1 ? Math.floor(length / 2) : Math.round((column / (width - 1)) * Math.max(0, length - 1));
  return center - Math.floor(fftSize / 2);
}

export class SpectrogramAccumulator {
  readonly width: number;
  private readonly minMidi: number;
  private readonly maxMidi: number;
  private readonly height: number;
  private readonly decibels: Float32Array;
  private readonly real: Float32Array;
  private readonly imaginary: Float32Array;
  private readonly window: Float32Array;
  private maximumDb = SILENCE_DB;

  constructor(private readonly sampleRate: number, width: number, minMidi: number, maxMidi: number, private readonly fftSize = DEFAULT_FFT_SIZE) {
    if (fftSize < 2 || (fftSize & (fftSize - 1)) !== 0) throw new Error("Spectrogram FFT size must be a power of two.");
    this.width = Math.max(1, Math.floor(width));
    this.minMidi = Math.round(Math.min(minMidi, maxMidi));
    this.maxMidi = Math.round(Math.max(minMidi, maxMidi));
    this.height = this.maxMidi - this.minMidi + 1;
    this.decibels = new Float32Array(this.width * this.height);
    this.real = new Float32Array(fftSize);
    this.imaginary = new Float32Array(fftSize);
    this.window = Float32Array.from({ length: fftSize }, (_, index) => 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / (fftSize - 1)));
  }

  addFrame(column: number, samples: Float32Array): void {
    const { real, imaginary, fftSize } = this;
    for (let index = 0; index < fftSize; index += 1) {
      real[index] = (samples[index] ?? 0) * this.window[index]!;
      imaginary[index] = 0;
    }
    fft(real, imaginary);

    for (let row = 0; row < this.height; row += 1) {
      const midi = this.maxMidi - row;
      const bin = (midiFrequency(midi) * fftSize) / this.sampleRate;
      const lowerBin = Math.max(1, Math.floor(bin / 2 ** (1 / 24)));
      const upperBin = Math.min(fftSize / 2 - 1, Math.ceil(bin * 2 ** (1 / 24)));
      let energy = 0;
      let count = 0;

      for (let binIndex = lowerBin; binIndex <= upperBin; binIndex += 1) {
        energy += real[binIndex]! ** 2 + imaginary[binIndex]! ** 2;
        count += 1;
      }

      const magnitude = count > 0 ? Math.sqrt(energy / count) / fftSize : 0;
      const db = magnitude > 0 ? 20 * Math.log10(magnitude) : SILENCE_DB;
      this.decibels[column * this.height + row] = db;
      this.maximumDb = Math.max(this.maximumDb, db);
    }
  }

  finish(): SpectrogramData {
    const values = new Uint8Array(this.decibels.length);
    if (this.maximumDb > SILENCE_DB) {
      const floorDb = this.maximumDb - DECIBEL_RANGE;
      for (let index = 0; index < this.decibels.length; index += 1) {
        const normalized = Math.min(1, Math.max(0, (this.decibels[index]! - floorDb) / DECIBEL_RANGE));
        values[index] = Math.round(255 * normalized ** 0.72);
      }
    }

    return {
      width: this.width,
      height: this.height,
      minMidi: this.minMidi,
      maxMidi: this.maxMidi,
      values,
    };
  }
}

function fft(real: Float32Array, imaginary: Float32Array): void {
  const size = real.length;
  for (let index = 1, reversed = 0; index < size; index += 1) {
    let bit = size >> 1;
    while (reversed & bit) {
      reversed ^= bit;
      bit >>= 1;
    }
    reversed ^= bit;
    if (index < reversed) {
      [real[index], real[reversed]] = [real[reversed]!, real[index]!];
      [imaginary[index], imaginary[reversed]] = [imaginary[reversed]!, imaginary[index]!];
    }
  }

  for (let length = 2; length <= size; length <<= 1) {
    const angle = (-2 * Math.PI) / length;
    const baseReal = Math.cos(angle);
    const baseImaginary = Math.sin(angle);
    for (let offset = 0; offset < size; offset += length) {
      let rotationReal = 1;
      let rotationImaginary = 0;
      for (let index = 0; index < length / 2; index += 1) {
        const even = offset + index;
        const odd = even + length / 2;
        const oddReal = real[odd]! * rotationReal - imaginary[odd]! * rotationImaginary;
        const oddImaginary = real[odd]! * rotationImaginary + imaginary[odd]! * rotationReal;
        const evenReal = real[even]!;
        const evenImaginary = imaginary[even]!;

        real[even] = evenReal + oddReal;
        imaginary[even] = evenImaginary + oddImaginary;
        real[odd] = evenReal - oddReal;
        imaginary[odd] = evenImaginary - oddImaginary;

        const nextRotationReal = rotationReal * baseReal - rotationImaginary * baseImaginary;
        rotationImaginary = rotationReal * baseImaginary + rotationImaginary * baseReal;
        rotationReal = nextRotationReal;
      }
    }
  }
}
