import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock, listenMock, saveMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  listenMock: vi.fn(),
  saveMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/api/event", () => ({ listen: listenMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: saveMock }));

import { describePlayerPackage, TauriPlayerExportService } from "./playerExportService";
import { createDefaultTracks } from "../domain/mixer";

const MIX = { currentTimeSeconds: 3, startMarkerSeconds: 12, masterVolume: 0.5, tracks: createDefaultTracks() };

describe("TauriPlayerExportService", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
    saveMock.mockReset();
  });

  it("suggests a .stems.zip named after the song", async () => {
    saveMock.mockResolvedValue("/Users/me/Desktop/My Song.stems.zip");
    await new TauriPlayerExportService().chooseDestination("/music/My Song.wav");
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({
      defaultPath: "My Song.stems.zip",
      filters: [{ name: "iPhone song package", extensions: ["zip"] }],
    }));
  });

  it("sends the mix, relays progress and stops listening afterwards", async () => {
    const unlisten = vi.fn();
    listenMock.mockImplementation(async (_event, handler) => {
      handler({ payload: { type: "export_progress", progress: 0.4, message: "Converting the vocals stem" } });
      handler({ payload: { type: "other" } });
      return unlisten;
    });
    invokeMock.mockResolvedValue({ path: "/out/Song.stems.zip", tempoBpm: 152, tempoSource: "bass transcription" });
    const progress = vi.fn();

    const result = await new TauriPlayerExportService().export("/project", "/out/Song.stems.zip", "Song.wav", MIX, progress);

    expect(listenMock).toHaveBeenCalledWith("player-export-event", expect.any(Function));
    expect(invokeMock).toHaveBeenCalledWith("export_player_package", {
      projectPath: "/project",
      destinationPath: "/out/Song.stems.zip",
      sourceName: "Song.wav",
      mix: MIX,
    });
    expect(progress).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledWith({ progress: 0.4, message: "Converting the vocals stem" });
    expect(result.tempoBpm).toBe(152);
    expect(unlisten).toHaveBeenCalled();
  });

  it("rejects a malformed result and still stops listening", async () => {
    const unlisten = vi.fn();
    listenMock.mockResolvedValue(unlisten);
    invokeMock.mockResolvedValue({ path: 3 });
    await expect(new TauriPlayerExportService().export("/p", "/o.zip", "s", MIX, vi.fn())).rejects.toThrow(/invalid/);
    expect(unlisten).toHaveBeenCalled();
  });

  it("says where the tempo came from, or that there is none", () => {
    expect(describePlayerPackage({ path: "/out/Song.stems.zip", tempoBpm: 152, tempoSource: "bass transcription" }))
      .toBe("Exported Song.stems.zip for iPhone · metronome from the bass transcription");
    expect(describePlayerPackage({ path: "/out/Song.stems.zip", tempoBpm: null, tempoSource: null }))
      .toBe("Exported Song.stems.zip for iPhone · no tempo found, so no metronome");
  });
});
