import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { Header } from "./components/Header";
import { TrackControls } from "./components/TrackControls";
import { useProjectStore } from "./state/projectStore";
import { AudioEngine } from "./audio/AudioEngine";
import { TauriSeparationService } from "./services/separationService";
import { TauriSessionService } from "./services/sessionService";
import type { SeparationResult, StemName } from "./domain/types";

vi.mock("./components/Header", async (original) => {
  const module = await original<typeof import("./components/Header")>();
  return { Header: vi.fn(module.Header) };
});
vi.mock("./components/TrackControls", async (original) => {
  const module = await original<typeof import("./components/TrackControls")>();
  return { TrackControls: vi.fn(module.TrackControls) };
});
const webview = vi.hoisted(() => ({ subscribe: vi.fn() }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: webview.subscribe }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const result: SeparationResult = {
  projectId: "test", projectPath: "/test", qualityProfile: "standard",
  stems: { vocals: "/vocals.wav", drums: "/drums.wav", bass: "/bass.wav", other: "/other.wav" },
};
const waveforms = Object.fromEntries(Object.keys(result.stems).map((name) => [name, new Float32Array(4)])) as Record<StemName, Float32Array>;

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  useProjectStore.getState().reset();
  window.history.replaceState({}, "", "/");
  webview.subscribe.mockResolvedValue(vi.fn());
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function button(selector: string) { return container.querySelector<HTMLButtonElement>(selector)!; }

describe("project playback rendering", () => {
  it("updates the playhead and clock without rerendering the header or track controls", async () => {
    window.history.replaceState({}, "", "/?demo=ready");
    await act(async () => root.render(createElement(App)));
    vi.mocked(Header).mockClear();
    vi.mocked(TrackControls).mockClear();
    for (let frame = 0; frame < 60; frame += 1) {
      await act(async () => useProjectStore.getState().setCurrentTime(100 + frame / 60));
    }
    expect(Header).not.toHaveBeenCalled();
    expect(TrackControls).not.toHaveBeenCalled();
    expect(container.querySelector(".transport-clock strong")?.textContent).toContain("01:40");
    expect(parseFloat(container.querySelector<HTMLElement>(".playhead")!.style.left)).toBeGreaterThan(39);
  });
});

describe("project import lifecycle", () => {
  beforeEach(() => vi.stubGlobal("__TAURI_INTERNALS__", {}));

  it("serializes dialogs and drops, and ignores progress and completion after cancellation", async () => {
    const dialog = deferred<string | null>();
    const separation = deferred<SeparationResult>();
    const choose = vi.spyOn(TauriSeparationService.prototype, "chooseFile").mockReturnValue(dialog.promise);
    const separate = vi.spyOn(TauriSeparationService.prototype, "separate").mockReturnValue(separation.promise);
    vi.spyOn(TauriSeparationService.prototype, "cancel").mockResolvedValue();
    const load = vi.spyOn(AudioEngine.prototype, "load");
    await act(async () => root.render(createElement(App)));
    await act(async () => {
      button(".import-button").click();
      button(".import-button").click();
      webview.subscribe.mock.calls.at(-1)![0]({ payload: { type: "drop", paths: ["/second.wav"] } });
    });
    expect(choose).toHaveBeenCalledTimes(1);
    expect(separate).not.toHaveBeenCalled();
    await act(async () => dialog.resolve("/first.wav"));
    expect(separate).toHaveBeenCalledTimes(1);
    await act(async () => button(".processing-view button").click());
    await act(async () => {
      separate.mock.calls[0]![2]({ type: "progress", progress: 0.9, message: "Late progress" });
      separation.resolve(result);
    });
    expect(load).not.toHaveBeenCalled();
    expect(useProjectStore.getState().status).toBe("empty");
    expect(useProjectStore.getState().source).toBeNull();
  });

  it("does not publish a decoded project after cancelling during audio loading", async () => {
    vi.spyOn(TauriSeparationService.prototype, "chooseFile").mockResolvedValue("/first.wav");
    vi.spyOn(TauriSeparationService.prototype, "separate").mockResolvedValue(result);
    const decoding = deferred<Record<StemName, Float32Array>>();
    vi.spyOn(AudioEngine.prototype, "load").mockReturnValue(decoding.promise);
    await act(async () => root.render(createElement(App)));
    await act(async () => button(".import-button").click());
    expect(useProjectStore.getState().status).toBe("loading");
    await act(async () => button(".processing-view button").click());
    await act(async () => decoding.resolve(waveforms));
    expect(useProjectStore.getState().status).toBe("empty");
    expect(useProjectStore.getState().waveforms).toEqual({});
  });

  it("blocks an import while a session dialog is open and releases it if dismissed", async () => {
    const dialog = deferred<string | null>();
    vi.spyOn(TauriSessionService.prototype, "chooseManifest").mockReturnValue(dialog.promise);
    const choose = vi.spyOn(TauriSeparationService.prototype, "chooseFile").mockResolvedValue(null);
    await act(async () => root.render(createElement(App)));
    await act(async () => {
      button('[aria-label="Open saved session"]').click();
      button(".import-button").click();
    });
    expect(choose).not.toHaveBeenCalled();
    await act(async () => dialog.resolve(null));
    await act(async () => button(".import-button").click());
    expect(choose).toHaveBeenCalledTimes(1);
  });

  it("unsubscribes a drag/drop listener that resolves after unmount", async () => {
    const subscription = deferred<() => void>();
    const cleanup = vi.fn();
    webview.subscribe.mockReturnValue(subscription.promise);
    await act(async () => root.render(createElement(App)));
    await act(async () => root.unmount());
    await act(async () => subscription.resolve(cleanup));
    expect(cleanup).toHaveBeenCalledTimes(1);
  });
});
