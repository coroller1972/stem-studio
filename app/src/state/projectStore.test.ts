import { beforeEach, describe, expect, it } from "vitest";
import { createDefaultTracks } from "../domain/mixer";
import { useProjectStore } from "./projectStore";

describe("projectStore master volume", () => {
  beforeEach(() => {
    useProjectStore.getState().reset();
    useProjectStore.setState({ masterVolume: 1 });
  });

  it("clamps the value and preserves it across project lifecycle changes", () => {
    useProjectStore.getState().setMasterVolume(0.37);
    useProjectStore.getState().beginImport("/music/song.mp3");
    expect(useProjectStore.getState().masterVolume).toBe(0.37);

    useProjectStore.getState().reset();
    expect(useProjectStore.getState().masterVolume).toBe(0.37);

    useProjectStore.getState().setMasterVolume(-2);
    expect(useProjectStore.getState().masterVolume).toBe(0);
    useProjectStore.getState().setMasterVolume(3);
    expect(useProjectStore.getState().masterVolume).toBe(1);
  });

  it("restores playback and mixer state before decoded audio becomes ready", () => {
    const tracks = createDefaultTracks();
    tracks.vocals = { volume: 0.42, muted: true, solo: false };
    tracks.drums = { volume: 0.8, muted: false, solo: true };

    useProjectStore.getState().restoreSession(
      "/sessions/song.stemstudio/session.json",
      "/sessions/song.stemstudio",
      "song.mp3",
      {
        vocals: "/sessions/song.stemstudio/vocals.wav",
        drums: "/sessions/song.stemstudio/drums.wav",
        bass: "/sessions/song.stemstudio/bass.wav",
        other: "/sessions/song.stemstudio/other.wav",
      },
      {
        currentTimeSeconds: 52,
        startMarkerSeconds: 48,
        masterVolume: 0.65,
        tracks,
      },
      { bass: null, drums: null },
      "high",
    );

    let state = useProjectStore.getState();
    expect(state.status).toBe("loading");
    expect(state.sessionPath).toBe("/sessions/song.stemstudio");
    expect(state.separationQuality).toBe("high");
    expect(state.masterVolume).toBe(0.65);
    expect(state.tracks.vocals).toEqual({ volume: 0.42, muted: true, solo: false });
    expect(state.tracks).not.toBe(tracks);

    const waveforms = {
      vocals: new Float32Array([0.1]),
      drums: new Float32Array([0.2]),
      bass: new Float32Array([0.3]),
      other: new Float32Array([0.4]),
    };
    state.setReady(50, waveforms);
    state = useProjectStore.getState();
    expect(state.status).toBe("ready");
    expect(state.currentTime).toBe(50);
    expect(state.startMarkerSeconds).toBe(48);
  });

  it("remembers the saved session independently from the working project", () => {
    useProjectStore.getState().beginImport("/music/song.mp3");
    useProjectStore.getState().setSeparated("/tmp/stem-project", {
      vocals: "/tmp/stem-project/vocals.wav",
      drums: "/tmp/stem-project/drums.wav",
      bass: "/tmp/stem-project/bass.wav",
      other: "/tmp/stem-project/other.wav",
    }, "standard");

    useProjectStore.getState().setSavedSession("/sessions/song.stemstudio");

    const state = useProjectStore.getState();
    expect(state.projectPath).toBe("/tmp/stem-project");
    expect(state.sessionPath).toBe("/sessions/song.stemstudio");
    expect(state.source?.path).toBe("/music/song.mp3");
  });
});
