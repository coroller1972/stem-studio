import type { SpectralStemName, SpectrogramData } from "../domain/types";

const DEFAULT_FFT_SIZE = 8_192;
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
  if (fftSize < 2 || (fftSize & (fftSize - 1)) !== 0) {
    throw new Error("Spectrogram FFT size must be a power of two.");
  }
  const safeWidth = Math.max(1, Math.floor(width));
  const safeMinMidi = Math.round(Math.min(minMidi, maxMidi));
  const safeMaxMidi = Math.round(Math.max(minMidi, maxMidi));
  const height = safeMaxMidi - safeMinMidi + 1;
  const decibels = new Float32Array(safeWidth * height);
  const real = new Float32Array(fftSize);
  const imaginary = new Float32Array(fftSize);
  let maximumDb = SILENCE_DB;

  for (let column = 0; column < safeWidth; column += 1) {
    const center = safeWidth === 1
      ? Math.floor(samples.length / 2)
      : Math.round((column / (safeWidth - 1)) * Math.max(0, samples.length - 1));
    const start = center - Math.floor(fftSize / 2);

    for (let index = 0; index < fftSize; index += 1) {
      const sampleIndex = start + index;
      const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / Math.max(1, fftSize - 1));
      real[index] = (samples[sampleIndex] ?? 0) * window;
      imaginary[index] = 0;
    }

    fft(real, imaginary);

    for (let row = 0; row < height; row += 1) {
      const midi = safeMaxMidi - row;
      const bin = (midiFrequency(midi) * fftSize) / sampleRate;
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
      decibels[column * height + row] = db;
      maximumDb = Math.max(maximumDb, db);
    }
  }

  const values = new Uint8Array(decibels.length);
  if (maximumDb > SILENCE_DB) {
    const floorDb = maximumDb - DECIBEL_RANGE;
    for (let index = 0; index < decibels.length; index += 1) {
      const normalized = Math.min(1, Math.max(0, (decibels[index]! - floorDb) / DECIBEL_RANGE));
      values[index] = Math.round(255 * normalized ** 0.72);
    }
  }

  return {
    width: safeWidth,
    height,
    minMidi: safeMinMidi,
    maxMidi: safeMaxMidi,
    values,
  };
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
