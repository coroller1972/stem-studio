import { convertFileSrc } from "@tauri-apps/api/core";
import { DEFAULT_FFT_SIZE, SPECTROGRAM_BATCH_COLUMNS, spectrogramFrameStart, spectrogramRange } from "./spectrogram";
import { calculateEffectiveGains, clampVolume } from "../domain/mixer";
import {
  STEM_NAMES,
  type SpectralStemName,
  type SpectrogramData,
  type StemName,
  type StemPaths,
  type StemState,
} from "../domain/types";
import { clampTime } from "../domain/transport";

type AudioContextFactory = () => AudioContext;
type BinaryLoader = (path: string, signal?: AbortSignal) => Promise<ArrayBuffer>;

const START_LATENCY_SECONDS = 0.05;
const MAX_AUDIO_DURATION_SECONDS = 30 * 60;

export class AudioEngine {
  private context: AudioContext | null = null;
  private readonly contextFactory: AudioContextFactory;
  private readonly binaryLoader: BinaryLoader;
  private buffers: Partial<Record<StemName, AudioBuffer>> = {};
  private gains: Partial<Record<StemName, GainNode>> = {};
  private masterGain: GainNode | null = null;
  private masterVolume = 1;
  private sources: Partial<Record<StemName, AudioBufferSourceNode>> = {};
  private offsetSeconds = 0;
  private contextStartedAt = 0;
  private playing = false;
  private generation = 0;
  private loadGeneration = 0;
  private loadController: AbortController | null = null;
  private loadedDuration = 0;
  private spectrograms: Partial<Record<SpectralStemName, Promise<SpectrogramData>>> = {};
  private spectrogramWorkers = new Map<Worker, () => void>();

  constructor(
    contextFactory: AudioContextFactory = () => new AudioContext(),
    binaryLoader: BinaryLoader = loadBinary,
  ) {
    this.contextFactory = contextFactory;
    this.binaryLoader = binaryLoader;
  }

  get duration(): number {
    return this.loadedDuration;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get currentTime(): number {
    if (!this.playing || !this.context) return this.offsetSeconds;
    const elapsed = Math.max(0, this.context.currentTime - this.contextStartedAt);
    return clampTime(this.offsetSeconds + elapsed, this.loadedDuration);
  }

  async load(stems: StemPaths): Promise<Record<StemName, Float32Array>> {
    this.clear();
    const loadGeneration = this.loadGeneration;
    const controller = new AbortController();
    this.loadController = controller;
    const context = this.ensureContext();
    const decoded: Array<readonly [StemName, AudioBuffer]> = [];
    const assertCurrentLoad = () => {
      if (loadGeneration !== this.loadGeneration) {
        throw new Error("Audio loading was cancelled because the project changed.");
      }
    };
    // Decode one stem at a time to avoid retaining four encoded WAVs and their copies.
    for (const name of STEM_NAMES) {
      const binary = await this.binaryLoader(stems[name], controller.signal);
      assertCurrentLoad();
      const buffer = await context.decodeAudioData(binary);
      assertCurrentLoad();
      if (!Number.isFinite(buffer.duration) || buffer.duration <= 0) {
        throw new Error("The audio stem has an invalid duration.");
      }
      if (buffer.duration > MAX_AUDIO_DURATION_SECONDS) {
        throw new Error("Stem Studio supports projects up to 30 minutes long.");
      }
      decoded.push([name, buffer]);
    }

    this.buffers = Object.fromEntries(decoded) as Record<StemName, AudioBuffer>;
    this.loadedDuration = Math.min(...decoded.map(([, buffer]) => buffer.duration));

    for (const name of STEM_NAMES) this.gains[name]?.disconnect();
    this.gains = {};
    this.masterGain?.disconnect();
    this.masterGain = context.createGain();
    this.masterGain.gain.value = this.masterVolume;
    this.masterGain.connect(context.destination);

    for (const name of STEM_NAMES) {
      const gain = context.createGain();
      gain.connect(this.masterGain);
      this.gains[name] = gain;
    }

    return Object.fromEntries(
      STEM_NAMES.map((name) => [name, extractPeaks(this.buffers[name]!, 1_200)]),
    ) as Record<StemName, Float32Array>;
  }

  getSpectrogram(name: SpectralStemName): Promise<SpectrogramData> {
    const cached = this.spectrograms[name];
    if (cached) return cached;
    const buffer = this.buffers[name];
    if (!buffer) return Promise.reject(new Error(`The ${name} stem is not loaded.`));

    const loadGeneration = this.loadGeneration;
    const width = Math.min(1_600, Math.max(320, Math.ceil(buffer.duration * 8)));
    const range = spectrogramRange(name);
    const worker = new Worker(new URL("./spectrogram.worker.ts", import.meta.url), { type: "module" });

    const request = new Promise<SpectrogramData>((resolve, reject) => {
      const finish = () => {
        worker.terminate();
        this.spectrogramWorkers.delete(worker);
      };
      this.spectrogramWorkers.set(worker, () => {
        finish();
        reject(new Error("The frequency view was cancelled because the audio project changed."));
      });
      worker.onmessage = (event: MessageEvent<
        | { type: "frames-needed"; column: number; count: number }
        | { type: "result"; result: SpectrogramData }
        | { type: "error"; message: string }
      >) => {
        if (event.data.type === "frames-needed" && loadGeneration === this.loadGeneration) {
          try {
            const samples = extractSpectrogramFrames(buffer, event.data.column, event.data.count, width);
            worker.postMessage({ type: "frames", samples: samples.buffer }, [samples.buffer]);
          } catch (error) {
            finish();
            reject(error);
          }
          return;
        }
        finish();
        if (loadGeneration !== this.loadGeneration) {
          reject(new Error("The audio project changed while the frequency view was being prepared."));
        } else if (event.data.type === "result") {
          resolve(event.data.result);
        } else if (event.data.type === "error") {
          reject(new Error(event.data.message));
        }
      };
      worker.onerror = (event) => {
        finish();
        reject(new Error(event.message || "Unable to calculate the frequency view."));
      };
      try {
        worker.postMessage({ type: "start", sampleRate: buffer.sampleRate, width, ...range });
      } catch (error) {
        finish();
        reject(error);
      }
    });

    this.spectrograms[name] = request;
    void request.catch(() => {
      if (this.spectrograms[name] === request) delete this.spectrograms[name];
    });
    return request;
  }

  async play(seconds = this.offsetSeconds): Promise<void> {
    if (!this.hasAllBuffers() || this.loadedDuration <= 0) return;
    const context = this.ensureContext();
    const playGeneration = ++this.generation;
    await context.resume();
    if (playGeneration !== this.generation) return;
    const offset = clampTime(seconds, this.loadedDuration);
    if (offset >= this.loadedDuration) return;

    this.stopSources();
    this.offsetSeconds = offset;
    const startAt = context.currentTime + START_LATENCY_SECONDS;
    this.contextStartedAt = startAt;
    this.playing = true;
    const generation = ++this.generation;

    for (const name of STEM_NAMES) {
      const source = context.createBufferSource();
      source.buffer = this.buffers[name]!;
      source.connect(this.gains[name]!);
      source.start(startAt, offset);
      this.sources[name] = source;
    }

    this.sources.vocals!.onended = () => {
      if (generation !== this.generation || !this.playing) return;
      this.offsetSeconds = this.loadedDuration;
      this.playing = false;
      this.sources = {};
    };
  }

  pause(): number {
    const at = this.currentTime;
    this.stopSources();
    this.offsetSeconds = at;
    return at;
  }

  async seek(seconds: number): Promise<number> {
    const next = clampTime(seconds, this.loadedDuration);
    const shouldResume = this.playing;
    this.stopSources();
    this.offsetSeconds = next;
    if (shouldResume && next < this.loadedDuration) await this.play(next);
    return next;
  }

  setTrackStates(tracks: Record<StemName, StemState>): void {
    const effective = calculateEffectiveGains(tracks);
    const context = this.context;
    if (!context) return;
    for (const name of STEM_NAMES) {
      const gain = this.gains[name]?.gain;
      if (!gain) continue;
      gain.cancelScheduledValues(context.currentTime);
      gain.setTargetAtTime(effective[name], context.currentTime, 0.008);
    }
  }

  setMasterVolume(volume: number): void {
    this.masterVolume = clampVolume(volume);
    const context = this.context;
    const gain = this.masterGain?.gain;
    if (!context || !gain) return;
    gain.cancelScheduledValues(context.currentTime);
    gain.setTargetAtTime(this.masterVolume, context.currentTime, 0.008);
  }

  clear(): void {
    this.loadController?.abort();
    this.loadController = null;
    this.stopSources();
    this.loadGeneration += 1;
    this.clearSpectrograms();
    for (const name of STEM_NAMES) this.gains[name]?.disconnect();
    this.masterGain?.disconnect();
    this.gains = {};
    this.masterGain = null;
    this.buffers = {};
    this.loadedDuration = 0;
    this.offsetSeconds = 0;
  }

  async dispose(): Promise<void> {
    this.clear();
    const context = this.context;
    this.context = null;
    if (context) await context.close();
  }

  private ensureContext(): AudioContext {
    this.context ??= this.contextFactory();
    return this.context;
  }

  private stopSources(): void {
    this.generation += 1;
    this.playing = false;
    for (const name of STEM_NAMES) {
      const source = this.sources[name];
      if (!source) continue;
      source.onended = null;
      try {
        source.stop();
      } catch {
        // A source can already have naturally ended.
      }
      source.disconnect();
    }
    this.sources = {};
  }

  private hasAllBuffers(): boolean {
    return STEM_NAMES.every((name) => this.buffers[name] !== undefined);
  }

  private clearSpectrograms(): void {
    for (const cancel of this.spectrogramWorkers.values()) cancel();
    this.spectrogramWorkers.clear();
    this.spectrograms = {};
  }
}

async function loadBinary(path: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const source = isTauriRuntime() ? convertFileSrc(path) : path;
  const response = await fetch(source, { signal: signal ?? null });
  if (!response.ok) throw new Error(`Unable to read audio stem (${response.status}).`);
  return response.arrayBuffer();
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function extractPeaks(buffer: AudioBuffer, targetLength: number): Float32Array {
  const channels = audioChannels(buffer);
  const length = buffer.length || channels[0]!.length;
  const count = Math.min(targetLength, length);
  const peaks = new Float32Array(count);
  const stride = length / count;

  for (let index = 0; index < count; index += 1) {
    const start = Math.floor(index * stride);
    const end = Math.max(start + 1, Math.floor((index + 1) * stride));
    let peak = 0;
    for (let sample = start; sample < end; sample += 1) {
      let mono = 0;
      for (const channel of channels) mono = Math.fround(mono + (channel[sample] ?? 0) / channels.length);
      peak = Math.max(peak, Math.abs(mono));
    }
    peaks[index] = peak;
  }
  return peaks;
}

export function mixChannels(buffer: AudioBuffer): Float32Array {
  const channels = Math.max(1, buffer.numberOfChannels || 1);
  const length = buffer.length || buffer.getChannelData(0).length;
  const mono = new Float32Array(length);
  for (let channelIndex = 0; channelIndex < channels; channelIndex += 1) {
    const channel = buffer.getChannelData(channelIndex);
    for (let sample = 0; sample < length; sample += 1) {
      mono[sample] = (mono[sample] ?? 0) + (channel[sample] ?? 0) / channels;
    }
  }
  return mono;
}

function audioChannels(buffer: AudioBuffer): Float32Array[] {
  return Array.from({ length: Math.max(1, buffer.numberOfChannels || 1) }, (_, index) => buffer.getChannelData(index));
}

// At most 1 MiB of PCM per worker request, independent of track duration.
export function extractSpectrogramFrames(buffer: AudioBuffer, column: number, count: number, width: number): Float32Array {
  if (!Number.isInteger(column) || !Number.isInteger(count) || column < 0 || count < 1 || count > SPECTROGRAM_BATCH_COLUMNS || column + count > width) {
    throw new Error("Invalid frequency analysis window request.");
  }
  const channels = audioChannels(buffer);
  const length = buffer.length || channels[0]!.length;
  const frames = new Float32Array(count * DEFAULT_FFT_SIZE);
  for (let frame = 0; frame < count; frame += 1) {
    const start = spectrogramFrameStart(length, column + frame, width);
    for (const channel of channels) {
      for (let index = 0; index < DEFAULT_FFT_SIZE; index += 1) {
        const target = frame * DEFAULT_FFT_SIZE + index;
        frames[target] = frames[target]! + (channel[start + index] ?? 0) / channels.length;
      }
    }
  }
  return frames;
}
