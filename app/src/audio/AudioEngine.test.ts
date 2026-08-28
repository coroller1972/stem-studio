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
