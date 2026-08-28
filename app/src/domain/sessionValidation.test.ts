import { describe, expect, it } from "vitest";
import { parseRestoredSession } from "./sessionValidation";

function validSession() {
  const tracks = Object.fromEntries(
    ["vocals", "drums", "bass", "other"].map((name) => [name, { volume: 1, muted: false, solo: false }]),
  );
  return {
    sessionPath: "/sessions/song.stemstudio",
    manifestPath: "/sessions/song.stemstudio/session.json",
    sourceName: "song.mp3",
    qualityProfile: "high",
    stems: {
      vocals: "/sessions/song.stemstudio/vocals.wav",
      drums: "/sessions/song.stemstudio/drums.wav",
      bass: "/sessions/song.stemstudio/bass.wav",
      other: "/sessions/song.stemstudio/other.wav",
    },
    state: { currentTimeSeconds: 1, startMarkerSeconds: 0, masterVolume: 0.8, tracks },
    transcriptions: { bass: null, drums: null },
  };
}

describe("saved session runtime validation", () => {
  it("accepts a complete restored session", () => {
    const session = validSession() as any;
    expect(parseRestoredSession(session)).toBe(session);
  });

  it("rejects invalid mixer values", () => {
    const session = validSession();
    session.state.masterVolume = 2;
    expect(() => parseRestoredSession(session)).toThrow("state.masterVolume");
  });

  it("rejects a transcription whose track does not match its slot", () => {
    const session = validSession();
    session.transcriptions.bass = {
      eventsFile: "/bass.json",
      midiFile: "/bass.mid",
      musicXmlFile: "/bass.musicxml",
      transcription: {
        schemaVersion: 3,
        track: "drums",
        events: [],
        tempoMap: { bpm: 120, beats: [], timeSignature: { numerator: 4, denominator: 4 } },
        tuning: [28, 33, 38, 43],
        tab: [],
      },
    } as never;
    expect(() => parseRestoredSession(session)).toThrow("bass.track");
  });
});
