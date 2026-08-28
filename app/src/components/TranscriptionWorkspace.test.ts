import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BassTranscriptionView, measureAtTime } from "./TranscriptionWorkspace";
import type { BassTranscription, TempoMap, TrackTranscriptionState } from "../domain/types";

const tempoMap: TempoMap = {
  bpm: 120,
  beats: Array.from({ length: 12 }, (_, beatIndex) => ({
    beatIndex,
    timeSeconds: beatIndex * 0.5,
  })),
  timeSignature: { numerator: 4, denominator: 4 },
};

describe("measureAtTime", () => {
  it("follows the current four-beat measure", () => {
    expect(measureAtTime(0, tempoMap)).toBe(1);
    expect(measureAtTime(1.99, tempoMap)).toBe(1);
    expect(measureAtTime(2, tempoMap)).toBe(2);
    expect(measureAtTime(4.25, tempoMap)).toBe(3);
  });

  it("extrapolates after the final detected beat", () => {
    expect(measureAtTime(8, tempoMap)).toBe(5);
  });

  it("keeps the first measure when no beat grid is available", () => {
    expect(measureAtTime(30, { ...tempoMap, beats: [] })).toBe(1);
  });

  it("identifies an anacrusis before the configured first measure", () => {
    const delayedDownbeat = {
      ...tempoMap,
      beats: tempoMap.beats.map((beat) => ({ ...beat, timeSeconds: beat.timeSeconds + 0.5 })),
    };
    expect(measureAtTime(0.25, delayedDownbeat)).toBe(0);
    expect(measureAtTime(0.5, delayedDownbeat)).toBe(1);
  });
});

describe("tablature playback following", () => {
  const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    document.body.replaceChildren();
  });

  it("centers a newly active measure only while playback is running", async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("notation-scroll")) return rect(0, 400);
      if (this.dataset.measure === "2") return rect(500, 100);
      return rect(20, 100);
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
      return this.classList.contains("notation-scroll") ? 400 : 100;
    });

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => root.render(viewAt(0, false)));
    expect(scrollTo).not.toHaveBeenCalled();
    expect(container.querySelector('[data-measure="1"]')?.querySelectorAll(".tab-string")).toHaveLength(5);

    await act(async () => root.render(viewAt(2.1, true)));
    expect(scrollTo).toHaveBeenCalledOnce();
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 350 });
    expect(container.querySelector(".tab-measure.is-current")?.getAttribute("data-measure")).toBe("2");

    await act(async () => root.render(viewAt(4.1, false)));
    expect(scrollTo).toHaveBeenCalledOnce();
    expect(container.querySelector(".tab-measure.is-current")?.getAttribute("data-measure")).toBe("3");

    await act(async () => root.unmount());
  });

  it("keeps progress visible while re-transcribing an existing result", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const processingState: TrackTranscriptionState<BassTranscription> = {
      ...bassState,
      status: "processing",
      stage: "inference",
      progress: 0.42,
      message: "Transcribing bass notes",
    };

    await act(async () => root.render(viewAt(0, false, processingState)));

    const progress = container.querySelector<HTMLElement>('[role="progressbar"]');
    expect(progress?.getAttribute("aria-valuenow")).toBe("42");
    expect(progress?.querySelector<HTMLElement>("span")?.style.width).toBe("42%");
    expect(container.textContent).toContain("Transcribing bass notes · 42%");
    expect(container.querySelector<HTMLButtonElement>(".transcription-actions .ghost-button")?.disabled).toBe(true);

    await act(async () => root.unmount());
  });
});

describe("manual transcription timing", () => {
  it("uses the playback marker as the first measure before applying", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const onRequantize = vi.fn();

    await act(async () => root.render(createElement(BassTranscriptionView, {
      state: bassState,
      currentTime: 0,
      followPlayback: false,
      tuning: "beadg",
      engine: "basic-pitch",
      onTuningChange: vi.fn(),
      onEngineChange: vi.fn(),
      onTranscribe: vi.fn(),
      startMarkerSeconds: 1.25,
      onRequantize,
      onSeek: vi.fn(),
      onExport: vi.fn(),
    })));

    await act(async () => container.querySelector<HTMLButtonElement>(".timing-marker-button")?.click());
    await act(async () => container.querySelector<HTMLFormElement>(".timing-editor")?.requestSubmit());

    expect(onRequantize).toHaveBeenCalledWith(120, 1.25);
    await act(async () => root.unmount());
  });
});

function viewAt(
  currentTime: number,
  followPlayback: boolean,
  state: TrackTranscriptionState<BassTranscription> = bassState,
) {
  return createElement(BassTranscriptionView, {
    state,
    currentTime,
    followPlayback,
    tuning: "beadg",
    engine: "torchcrepe",
    onTuningChange: vi.fn(),
    onEngineChange: vi.fn(),
    onTranscribe: vi.fn(),
    startMarkerSeconds: 1.25,
    onRequantize: vi.fn(),
    onSeek: vi.fn(),
    onExport: vi.fn(),
  });
}

const bassTranscription: BassTranscription = {
  schemaVersion: 1,
  track: "bass",
  events: [0, 4, 8].map((quantizedStartBeat, index) => ({
    id: `note-${index}`,
    detectedStartSeconds: quantizedStartBeat / 2,
    detectedEndSeconds: quantizedStartBeat / 2 + 0.25,
    quantizedStartBeat,
    quantizedDurationBeats: 1,
    midiPitch: 40 + index,
    velocity: 100,
    confidence: 0.9,
  })),
  tab: [0, 4, 8].map((startBeat, index) => ({
    noteEventId: `note-${index}`,
    stringIndex: 0,
    fret: index,
    startBeat,
    durationBeats: 1,
  })),
  tempoMap,
  tuning: [23, 28, 33, 38, 43],
  warnings: [],
};

const bassState: TrackTranscriptionState<BassTranscription> = {
  status: "ready",
  stage: "completed",
  progress: 1,
  message: "Ready",
  error: null,
  result: {
    eventsFile: "/tmp/bass.json",
    midiFile: "/tmp/bass.mid",
    musicXmlFile: "/tmp/bass.musicxml",
    transcription: bassTranscription,
  },
};

function rect(top: number, height: number): DOMRect {
  return {
    x: 0,
    y: top,
    top,
    right: 280,
    bottom: top + height,
    left: 0,
    width: 280,
    height,
    toJSON: () => ({}),
  };
}
