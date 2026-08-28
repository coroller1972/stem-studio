import { convertFileSrc } from "@tauri-apps/api/core";
import { spectrogramRange } from "./spectrogram";
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
type BinaryLoader = (path: string) => Promise<ArrayBuffer>;

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
  private loadedDuration = 0;
  private spectrograms: Partial<Record<SpectralStemName, Promise<SpectrogramData>>> = {};
  private spectrogramWorkers = new Set<Worker>();

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
    this.stopSources();
    this.loadGeneration += 1;
    this.clearSpectrograms();
    const context = this.ensureContext();
    const decoded = await Promise.all(
      STEM_NAMES.map(async (name) => {
        const binary = await this.binaryLoader(stems[name]);
        const buffer = await context.decodeAudioData(binary.slice(0));
        return [name, buffer] as const;
      }),
    );

    this.buffers = Object.fromEntries(decoded) as Record<StemName, AudioBuffer>;
    this.loadedDuration = Math.min(...decoded.map(([, buffer]) => buffer.duration));
    if (this.loadedDuration > MAX_AUDIO_DURATION_SECONDS) {
      this.buffers = {};
      this.loadedDuration = 0;
      throw new Error("Stem Studio supports projects up to 30 minutes long.");
    }
    this.offsetSeconds = 0;

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
    const samples = mixChannels(buffer);
    const width = Math.min(1_600, Math.max(320, Math.ceil(buffer.duration * 8)));
    const range = spectrogramRange(name);
    const worker = new Worker(new URL("./spectrogram.worker.ts", import.meta.url), { type: "module" });
    this.spectrogramWorkers.add(worker);

    const request = new Promise<SpectrogramData>((resolve, reject) => {
      const finish = () => {
        worker.terminate();
        this.spectrogramWorkers.delete(worker);
      };
      worker.onmessage = (event: MessageEvent<
        | { type: "result"; result: SpectrogramData }
        | { type: "error"; message: string }
      >) => {
        finish();
        if (loadGeneration !== this.loadGeneration) {
          reject(new Error("The audio project changed while the frequency view was being prepared."));
        } else if (event.data.type === "result") {
          resolve(event.data.result);
        } else {
          reject(new Error(event.data.message));
        }
      };
      worker.onerror = (event) => {
        finish();
        reject(new Error(event.message || "Unable to calculate the frequency view."));
      };
      worker.postMessage(
        { samples: samples.buffer, sampleRate: buffer.sampleRate, width, ...range },
        [samples.buffer],
      );
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
    await context.resume();
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

  async dispose(): Promise<void> {
    this.stopSources();
    this.loadGeneration += 1;
    this.clearSpectrograms();
    for (const name of STEM_NAMES) this.gains[name]?.disconnect();
    this.masterGain?.disconnect();
    this.gains = {};
    this.masterGain = null;
    this.buffers = {};
    this.loadedDuration = 0;
    if (this.context) await this.context.close();
    this.context = null;
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
    for (const worker of this.spectrogramWorkers) worker.terminate();
    this.spectrogramWorkers.clear();
    this.spectrograms = {};
  }
}

async function loadBinary(path: string): Promise<ArrayBuffer> {
  const source = isTauriRuntime() ? convertFileSrc(path) : path;
  const response = await fetch(source);
  if (!response.ok) throw new Error(`Unable to read audio stem (${response.status}).`);
  return response.arrayBuffer();
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function extractPeaks(buffer: AudioBuffer, targetLength: number): Float32Array {
  const channel = mixChannels(buffer);
  const count = Math.min(targetLength, channel.length);
  const peaks = new Float32Array(count);
  const stride = channel.length / count;

  for (let index = 0; index < count; index += 1) {
    const start = Math.floor(index * stride);
    const end = Math.max(start + 1, Math.floor((index + 1) * stride));
    let peak = 0;
    for (let sample = start; sample < end; sample += 1) {
      peak = Math.max(peak, Math.abs(channel[sample] ?? 0));
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
