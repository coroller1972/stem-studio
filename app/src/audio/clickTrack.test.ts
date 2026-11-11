import { describe, expect, it, vi } from "vitest";
import { AudioEngine, type PlaybackClock } from "./AudioEngine";
import { ClickTrack } from "./clickTrack";
import { buildMetronomeGrid } from "../domain/metronome";
import { manualTempo } from "../domain/metronomeTempo";
import type { StemPaths } from "../domain/types";

const STEM_PATHS: StemPaths = { vocals: "/v.wav", drums: "/d.wav", bass: "/b.wav", other: "/o.wav" };

interface FakeSource {
  buffer: unknown;
  onended: null;
  destination: unknown;
  startedAt: number | null;
  stopped: boolean;
  connect: (node: unknown) => void;
  disconnect: () => void;
  start: (at: number, offset?: number) => void;
  stop: () => void;
}

/** An audio context that records every source started, with what it plays and where. */
function fakeContext(duration = 10) {
  const sources: FakeSource[] = [];
  const gains: Array<{ gain: { value: number; cancelScheduledValues: () => void; setTargetAtTime: ReturnType<typeof vi.fn> } }> = [];
  const context = {
    currentTime: 0,
    sampleRate: 8_000,
    destination: { name: "destination" },
    resume: vi.fn(async () => {}),
    close: vi.fn(async () => {}),
    decodeAudioData: vi.fn(async () => ({
      duration, numberOfChannels: 1, length: 4, getChannelData: () => new Float32Array(4),
    })),
    createBuffer: (_channels: number, length: number) => {
      const data = new Float32Array(length);
      return { getChannelData: () => data };
    },
    createGain: () => {
      const node = {
        gain: { value: 1, cancelScheduledValues: () => {}, setTargetAtTime: vi.fn() },
        connect: vi.fn(),
        disconnect: vi.fn(),
      };
      gains.push(node);
      return node;
    },
    createBufferSource: () => {
      const source: FakeSource = {
        buffer: null,
        onended: null,
        destination: null,
        startedAt: null,
        stopped: false,
        connect(node) { this.destination = node; },
        disconnect: () => {},
        start(at) { this.startedAt = at; },
        stop() { this.stopped = true; },
      };
      sources.push(source);
      return source;
    },
  };
  return { context, sources, gains, asContext: context as unknown as AudioContext };
}

/** 120 BPM in 4/4 with bar 1 at 0 s: a beat every 0.5 s, a bar every 2 s. */
function steadyGrid(bpm = 120, downbeat = 0, duration = 10) {
  const tempo = manualTempo(bpm, downbeat, duration)!;
  return buildMetronomeGrid(tempo.beats, tempo.beatsPerBar)!;
}

const clickSources = (sources: FakeSource[]) => sources.filter((source) => !source.stopped && source.startedAt !== null);
const times = (sources: FakeSource[]) => clickSources(sources).map((source) => source.startedAt!);

describe("ClickTrack", () => {
  it("schedules a count-in before the stems and the song's clicks on the stems' clock", () => {
    const { context, sources, asContext } = fakeContext();
    const track = new ClickTrack();
    track.setGrid(steadyGrid());
    track.setCountInBars(1);
    track.setSongClicks(true);
    expect(track.leadInSeconds(4)).toBeCloseTo(2, 6);

    // The stems start at context time 12.05 at song time 4, after a 2 s lead-in.
    const clock: PlaybackClock = { context: asContext, startAt: 12.05, offsetSeconds: 4, leadInSeconds: 2, duration: 6 };
    context.currentTime = 10;
    track.start(clock);
    const scheduled = times(sources);
    expect(scheduled.slice(0, 4)).toEqual([10.05, 10.55, 11.05, 11.55].map((time) => expect.closeTo(time, 6)));
    // Song clicks land exactly where their beat plays in the stems: song time t at 12.05 + t - 4.
    expect(scheduled.slice(4)).toEqual([12.05, 12.55, 13.05, 13.55].map((time) => expect.closeTo(time, 6)));
    const accents = clickSources(sources).map((source) => source.buffer);
    expect(accents[0]).toBe(accents[4]);
    expect(accents[0]).not.toBe(accents[1]);
  });

  it("does not count in without a lead-in, as when seeking during playback", () => {
    const { sources, asContext } = fakeContext();
    const track = new ClickTrack();
    track.setGrid(steadyGrid());
    track.setCountInBars(2);
    track.start({ context: asContext, startAt: 0.05, offsetSeconds: 3.2, leadInSeconds: 0, duration: 5 });
    expect(times(sources)).toEqual([0.35, 0.85, 1.35].map((time) => expect.closeTo(time, 6)));
  });

  it("restarts from the new position on every run and stops every pending click", () => {
    const { context, sources, asContext } = fakeContext();
    const track = new ClickTrack();
    track.setGrid(steadyGrid());
    track.start({ context: asContext, startAt: 0.05, offsetSeconds: 0, leadInSeconds: 0, duration: 10 });
    expect(clickSources(sources)).toHaveLength(20);
    context.currentTime = 1;
    track.start({ context: asContext, startAt: 1.05, offsetSeconds: 7.25, leadInSeconds: 0, duration: 10 });
    expect(times(sources)).toEqual([1.3, 1.8, 2.3, 2.8, 3.3].map((time) => expect.closeTo(time, 6)));
    track.stop();
    expect(clickSources(sources)).toHaveLength(0);
  });

  it("reschedules the rest of the song when the tempo changes mid-playback", () => {
    const { context, sources, asContext } = fakeContext();
    const track = new ClickTrack();
    track.setGrid(steadyGrid());
    track.start({ context: asContext, startAt: 0.05, offsetSeconds: 0, leadInSeconds: 0, duration: 4 });
    context.currentTime = 2.06;
    track.setGrid(steadyGrid(60));
    // Only future clicks, on the new one-second beat: song times 3 (context 3.05).
    expect(times(sources)).toEqual([expect.closeTo(3.05, 6)]);
    track.stop();
    track.setGrid(steadyGrid());
    expect(clickSources(sources)).toHaveLength(0);
  });

  it("mutes the song's clicks without touching the count-in", () => {
    const { gains, asContext } = fakeContext();
    const track = new ClickTrack();
    track.setGrid(steadyGrid());
    track.start({ context: asContext, startAt: 0.05, offsetSeconds: 0, leadInSeconds: 0, duration: 4 });
    const [output, song] = gains;
    expect(song!.gain.value).toBe(0);
    track.setSongClicks(true);
    expect(song!.gain.setTargetAtTime).toHaveBeenLastCalledWith(1, 0, 0.01);
    track.setVolume(2);
    expect(output!.gain.setTargetAtTime).toHaveBeenLastCalledWith(1, 0, 0.01);
  });
});

describe("ClickTrack with the AudioEngine", () => {
  it("keeps the clicks on the stems' beats through a count-in, a pause and a seek", async () => {
    const { context, sources, asContext } = fakeContext(10);
    const engine = new AudioEngine(() => asContext, async () => new ArrayBuffer(8));
    await engine.load(STEM_PATHS);
    const track = new ClickTrack();
    track.setGrid(steadyGrid(120, 0.25));
    track.setCountInBars(1);
    track.setSongClicks(true);
    engine.addPlaybackListener(track);

    const stems = () => sources.filter((source) => source.destination !== null && (source.buffer as { duration?: number })?.duration === 10);
    const clicks = () => clickSources(sources).filter((source) => !stems().includes(source));

    // Play from a start marker on the downbeat at 2.25 s: one bar of count-in first.
    await engine.play(2.25, track.leadInSeconds(2.25));
    const stemStart = stems()[0]!.startedAt!;
    expect(stemStart).toBeCloseTo(0.05 + 2, 6);
    const scheduled = clicks().map((source) => source.startedAt!);
    expect(scheduled.slice(0, 5)).toEqual([0.05, 0.55, 1.05, 1.55, 2.05].map((time) => expect.closeTo(time, 6)));
    expect(engine.currentTime).toBe(2.25);

    // Seek during playback to 5.4 s: no count-in, the next beat (5.75 s) clicks 0.35 s later.
    context.currentTime = 3;
    await engine.seek(5.4);
    const afterSeek = clicks().map((source) => source.startedAt!);
    expect(afterSeek[0]).toBeCloseTo(3 + 0.05 + 0.35, 6);
    expect(afterSeek[1]! - afterSeek[0]!).toBeCloseTo(0.5, 6);

    engine.pause();
    expect(clicks()).toHaveLength(0);
  });
});
