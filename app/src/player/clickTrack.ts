import type { PlaybackClock, PlaybackListener } from "../audio/AudioEngine";
import { countIn, songClicks, type MetronomeClick, type MetronomeGrid } from "./metronome";

const CLICK_SECONDS = 0.05;

/**
 * Plays metronome clicks in step with the stems. Every click of the song is
 * scheduled on the audio clock when playback starts, so the metronome keeps
 * time even while iOS throttles the page's timers behind a locked screen.
 */
export class ClickTrack implements PlaybackListener {
  private grid: MetronomeGrid | null = null;
  private countInBars = 0;
  private songClicksEnabled = false;
  private volume = 0.8;
  private context: AudioContext | null = null;
  private output: GainNode | null = null;
  private songGain: GainNode | null = null;
  private sounds: { accent: AudioBuffer; beat: AudioBuffer } | null = null;
  private scheduled: AudioBufferSourceNode[] = [];

  setGrid(grid: MetronomeGrid | null): void {
    this.grid = grid;
  }

  setCountInBars(bars: number): void {
    this.countInBars = Math.max(0, Math.floor(bars));
  }

  /** Mutes or unmutes the song's clicks immediately, mid-playback included. */
  setSongClicks(enabled: boolean): void {
    this.songClicksEnabled = enabled;
    this.ramp(this.songGain, enabled ? 1 : 0);
  }

  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    this.ramp(this.output, this.volume);
  }

  /** The silence playback needs before `startSeconds` for the count-in. */
  leadInSeconds(startSeconds: number): number {
    if (!this.grid || this.countInBars === 0) return 0;
    return countIn(this.grid, startSeconds, this.countInBars).leadInSeconds;
  }

  start({ context, startAt, offsetSeconds, leadInSeconds, duration }: PlaybackClock): void {
    this.stop();
    const grid = this.grid;
    if (!grid) return;
    this.connect(context);
    const toContextTime = (songTime: number) => startAt + songTime - offsetSeconds;
    if (leadInSeconds > 0 && this.countInBars > 0) {
      for (const click of countIn(grid, offsetSeconds, this.countInBars).clicks) {
        this.schedule(click, toContextTime(click.time), this.output!);
      }
    }
    for (const click of songClicks(grid, offsetSeconds, duration)) {
      this.schedule(click, toContextTime(click.time), this.songGain!);
    }
  }

  stop(): void {
    for (const node of this.scheduled) {
      try {
        node.stop();
      } catch {
        // A click that never started cannot be stopped twice.
      }
      node.disconnect();
    }
    this.scheduled = [];
  }

  private connect(context: AudioContext): void {
    if (this.context === context) return;
    this.context = context;
    this.output = context.createGain();
    this.output.gain.value = this.volume;
    this.output.connect(context.destination);
    this.songGain = context.createGain();
    this.songGain.gain.value = this.songClicksEnabled ? 1 : 0;
    this.songGain.connect(this.output);
    this.sounds = { accent: renderClick(context, 1_760, 1), beat: renderClick(context, 1_320, 0.7) };
  }

  private schedule(click: MetronomeClick, at: number, destination: AudioNode): void {
    const context = this.context!;
    if (at < context.currentTime) return;
    const node = context.createBufferSource();
    node.buffer = click.accent ? this.sounds!.accent : this.sounds!.beat;
    node.connect(destination);
    node.start(at);
    this.scheduled.push(node);
  }

  private ramp(node: GainNode | null, value: number): void {
    if (!node || !this.context) return;
    node.gain.cancelScheduledValues(this.context.currentTime);
    node.gain.setTargetAtTime(value, this.context.currentTime, 0.01);
  }
}

/** A short wood-block-like tick: two decaying partials that cut through a band. */
function renderClick(context: AudioContext, frequency: number, level: number): AudioBuffer {
  const length = Math.round(context.sampleRate * CLICK_SECONDS);
  const buffer = context.createBuffer(1, length, context.sampleRate);
  const samples = buffer.getChannelData(0);
  for (let index = 0; index < length; index += 1) {
    const time = index / context.sampleRate;
    const attack = Math.min(1, index / 24);
    const body = Math.sin(2 * Math.PI * frequency * time) * Math.exp(-time * 90);
    const overtone = 0.35 * Math.sin(2 * Math.PI * frequency * 2.76 * time) * Math.exp(-time * 160);
    samples[index] = level * 0.85 * attack * (body + overtone);
  }
  return buffer;
}
