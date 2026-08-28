import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock, openMock, saveMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  openMock: vi.fn(),
  saveMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: openMock, save: saveMock }));

import { TauriSessionService } from "./sessionService";

describe("TauriSessionService", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    openMock.mockReset();
    saveMock.mockReset();
  });

  it("uses a save dialog with a Stem Studio filename", async () => {
    saveMock.mockResolvedValue("/sessions/My Song.stemstudio");
    const service = new TauriSessionService();

    const selected = await service.chooseSessionPath("My Song.mp3");

    expect(selected).toBe("/sessions/My Song.stemstudio");
    expect(saveMock).toHaveBeenCalledWith({
      title: "Save Stem Studio session",
      defaultPath: "My Song.stemstudio",
      filters: [{ name: "Stem Studio session", extensions: ["stemstudio"] }],
    });
    expect(openMock).not.toHaveBeenCalled();
  });

  it("passes the exact session path to the Rust save command", async () => {
    invokeMock.mockResolvedValue({
      sessionPath: "/sessions/My Song.stemstudio",
      manifestPath: "/sessions/My Song.stemstudio/session.json",
    });
    const service = new TauriSessionService();
    const state = {
      currentTimeSeconds: 12,
      startMarkerSeconds: 8,
      masterVolume: 0.8,
      tracks: {
        vocals: { volume: 1, muted: false, solo: false },
        drums: { volume: 1, muted: false, solo: false },
        bass: { volume: 1, muted: false, solo: false },
        other: { volume: 1, muted: false, solo: false },
      },
    };

    await service.save(
      "/tmp/stem-project",
      "/sessions/My Song.stemstudio",
      "My Song.mp3",
      "high",
      state,
    );

    expect(invokeMock).toHaveBeenCalledWith("save_session", {
      projectPath: "/tmp/stem-project",
      sessionPath: "/sessions/My Song.stemstudio",
      sourceName: "My Song.mp3",
      qualityProfile: "high",
      state,
    });
  });
});
