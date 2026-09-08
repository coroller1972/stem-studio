import { describe, expect, it, vi } from "vitest";
import { AudioEngine, mixChannels } from "./AudioEngine";
import type { StemPaths } from "../domain/types";

const STEM_PATHS: StemPaths = {
  vocals: "/vocals.wav",
  drums: "/drums.wav",
  bass: "/bass.wav",
  other: "/other.wav",
};

describe("AudioEngine master volume", () => {
  it("mixes every decoded channel for waveforms and frequency analysis", () => {
    const channels = [new Float32Array([1, 0]), new Float32Array([0, -1])];
    const buffer = {
      numberOfChannels: 2,
      length: 2,
      getChannelData: (index: number) => channels[index]!,
    } as unknown as AudioBuffer;
    expect(Array.from(mixChannels(buffer))).toEqual([0.5, -0.5]);
  });
  it("routes every track through one master gain and updates it smoothly", async () => {
    const gainNodes: Array<{
      gain: {
        value: number;
        cancelScheduledValues: ReturnType<typeof vi.fn>;
        setTargetAtTime: ReturnType<typeof vi.fn>;
      };
      connect: ReturnType<typeof vi.fn>;
      disconnect: ReturnType<typeof vi.fn>;
    }> = [];
    const buffer = {
      duration: 1,
      numberOfChannels: 1,
      length: 4,
      getChannelData: () => new Float32Array([0.1, -0.4, 0.2, 0.3]),
    };
    const context = {
      currentTime: 2,
      destination: {},
      decodeAudioData: vi.fn(async () => buffer),
      createGain: vi.fn(() => {
        const node = {
          gain: {
            value: 1,
            cancelScheduledValues: vi.fn(),
            setTargetAtTime: vi.fn(),
          },
          connect: vi.fn(),
          disconnect: vi.fn(),
        };
        gainNodes.push(node);
        return node;
      }),
    };
    const engine = new AudioEngine(
      () => context as unknown as AudioContext,
      async () => new ArrayBuffer(8),
    );

    engine.setMasterVolume(0.65);
    await engine.load(STEM_PATHS);

    const master = gainNodes[0]!;
    const tracks = gainNodes.slice(1);
    expect(master.gain.value).toBe(0.65);
    expect(master.connect).toHaveBeenCalledWith(context.destination);
    expect(tracks).toHaveLength(4);
    for (const track of tracks) expect(track.connect).toHaveBeenCalledWith(master);

    engine.setMasterVolume(0.32);
    expect(master.gain.cancelScheduledValues).toHaveBeenCalledWith(2);
    expect(master.gain.setTargetAtTime).toHaveBeenLastCalledWith(0.32, 2, 0.008);

    engine.setMasterVolume(4);
    expect(master.gain.setTargetAtTime).toHaveBeenLastCalledWith(1, 2, 0.008);
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function audioFixture() {
  const buffer = {
    duration: 10, numberOfChannels: 1, length: 4,
    getChannelData: () => new Float32Array([0.1, -0.4, 0.2, 0.3]),
  } as unknown as AudioBuffer;
  const context = {
    currentTime: 0, destination: {},
    decodeAudioData: vi.fn(async (_binary: ArrayBuffer) => buffer),
    createGain: vi.fn(() => ({
      gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn(),
    })),
    resume: vi.fn(async () => {}), close: vi.fn(async () => {}),
    createBufferSource: vi.fn(),
  };
  return { buffer, context, factory: () => context as unknown as AudioContext };
}

describe("AudioEngine asynchronous lifecycle", () => {
  it("decodes stems sequentially without copying encoded data", async () => {
    const { context, factory, buffer } = audioFixture();
    const decoding = deferred<AudioBuffer>();
    context.decodeAudioData.mockImplementationOnce(() => decoding.promise);
    const binary = new ArrayBuffer(8);
    const loader = vi.fn(async () => binary);
    const engine = new AudioEngine(factory, loader);
    const loading = engine.load(STEM_PATHS);
    await Promise.resolve();
    expect(loader).toHaveBeenCalledTimes(1);
    expect(context.decodeAudioData.mock.calls[0]![0]).toBe(binary);
    decoding.resolve(buffer);
    await loading;
    expect(loader).toHaveBeenCalledTimes(4);
  });

  it("prevents an older load from overwriting the current project", async () => {
    const { factory } = audioFixture();
    const pending = deferred<ArrayBuffer>();
    const loader = vi.fn(async () => new ArrayBuffer(8));
    loader.mockImplementationOnce(() => pending.promise);
    const engine = new AudioEngine(factory, loader);
    const oldLoad = expect(engine.load(STEM_PATHS)).rejects.toThrow(/cancelled/);
    await engine.load(STEM_PATHS);
    pending.resolve(new ArrayBuffer(8));
    await oldLoad;
    expect(engine.duration).toBe(10);
    expect(loader).toHaveBeenCalledTimes(5);
  });

  it("does not restore buffers after disposal during decoding", async () => {
    const { context, factory, buffer } = audioFixture();
    const pending = deferred<AudioBuffer>();
    context.decodeAudioData.mockImplementationOnce(() => pending.promise);
    const engine = new AudioEngine(factory, async () => new ArrayBuffer(8));
    const loading = expect(engine.load(STEM_PATHS)).rejects.toThrow(/cancelled/);
    await Promise.resolve();
    await engine.dispose();
    pending.resolve(buffer);
    await loading;
    expect(engine.duration).toBe(0);
    expect(context.createGain).not.toHaveBeenCalled();
  });

  it("rejects an oversized stem even when other stems are shorter", async () => {
    const { context, factory, buffer } = audioFixture();
    context.decodeAudioData.mockResolvedValueOnce(buffer)
      .mockResolvedValueOnce({ ...buffer, duration: 1801 });
    const engine = new AudioEngine(factory, async () => new ArrayBuffer(8));
    await expect(engine.load(STEM_PATHS)).rejects.toThrow(/30 minutes/);
    expect(engine.duration).toBe(0);
    expect(context.decodeAudioData).toHaveBeenCalledTimes(2);
  });

  it("honors pause while the audio context is resuming", async () => {
    const { context, factory } = audioFixture();
    const engine = new AudioEngine(factory, async () => new ArrayBuffer(8));
    await engine.load(STEM_PATHS);
    const pending = deferred<void>();
    context.resume.mockImplementationOnce(() => pending.promise);
    const playing = engine.play();
    engine.pause();
    pending.resolve();
    await playing;
    expect(engine.isPlaying).toBe(false);
    expect(context.createBufferSource).not.toHaveBeenCalled();
  });

  it("settles pending spectrogram requests on disposal", async () => {
    const terminate = vi.fn();
    vi.stubGlobal("Worker", class {
      terminate = terminate;
      postMessage = vi.fn();
    });
    try {
      const { factory } = audioFixture();
      const engine = new AudioEngine(factory, async () => new ArrayBuffer(8));
      await engine.load(STEM_PATHS);
      const pending = expect(engine.getSpectrogram("bass")).rejects.toThrow(/cancelled/);
      await engine.dispose();
      await pending;
      expect(terminate).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("bounded waveform and frequency analysis", () => {
  it("streams the same stereo spectrum as a complete mono mix, including padded edges", async () => {
    const { extractSpectrogramFrames, extractPeaks } = await import("./AudioEngine");
    const { calculateSpectrogram, DEFAULT_FFT_SIZE, SpectrogramAccumulator } = await import("./spectrogram");
    const channels = [110, 220].map((frequency) => Float32Array.from({ length: 18000 }, (_, index) => Math.sin(2 * Math.PI * frequency * index / 44100)));
    const buffer = { length: 18000, numberOfChannels: 2, getChannelData: (index: number) => channels[index]! } as AudioBuffer;
    const mono = mixChannels(buffer);
    const accumulator = new SpectrogramAccumulator(44100, 65, 21, 84);
    for (let column = 0; column < 65; column += 32) {
      const frames = extractSpectrogramFrames(buffer, column, Math.min(32, 65 - column), 65);
      expect(frames.byteLength).toBeLessThanOrEqual(1024 * 1024);
      for (let offset = 0; offset < frames.length; offset += DEFAULT_FFT_SIZE) {
        accumulator.addFrame(column + offset / DEFAULT_FFT_SIZE, frames.subarray(offset, offset + DEFAULT_FFT_SIZE));
      }
    }
    expect(accumulator.finish()).toEqual(calculateSpectrogram(mono, 44100, 65, 21, 84));
    const peaks = extractPeaks(buffer, 12);
    for (let index = 0; index < peaks.length; index += 1) {
      expect(peaks[index]).toBe(Math.max(...Array.from(mono.subarray(index * 1500, (index + 1) * 1500), Math.abs)));
    }
  });

  it("keeps each PCM batch under 1 MiB even for a thirty-minute timeline", async () => {
    const { extractSpectrogramFrames } = await import("./AudioEngine");
    // Sparse stand-in: the declared length models long audio without allocating its PCM in the test.
    const buffer = { length: 48000 * 1800, numberOfChannels: 2, getChannelData: () => new Float32Array(0) } as unknown as AudioBuffer;
    expect(extractSpectrogramFrames(buffer, 800, 32, 1600).byteLength).toBe(1024 * 1024);
    expect(() => extractSpectrogramFrames(buffer, 0, 33, 1600)).toThrow(/Invalid/);
  });

  it("aborts an in-flight fetch when clearing the project", async () => {
    const { factory } = audioFixture();
    const loader = vi.fn((_path: string, signal?: AbortSignal) => new Promise<ArrayBuffer>((_resolve, reject) => {
      signal!.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
    }));
    const engine = new AudioEngine(factory, loader);
    const loading = expect(engine.load(STEM_PATHS)).rejects.toThrow(/cancelled/);
    engine.clear();
    await loading;
    expect(loader.mock.calls[0]![1]?.aborted).toBe(true);
    expect(engine.duration).toBe(0);
  });
});
