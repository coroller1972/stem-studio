// @vitest-environment node
import { describe, expect, it } from "vitest";
import { parseManifest, readStemPackage } from "./stemPackage";

const STEMS = { vocals: "vocals.m4a", drums: "drums.m4a", bass: "bass.m4a", other: "other.m4a" };

/** A minimal store-only ZIP writer (CRCs are not checked by the reader). */
function zip(files: Record<string, Uint8Array>, method = 0): Blob {
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  const directory: Uint8Array[] = [];
  let offset = 0;
  for (const [name, data] of Object.entries(files)) {
    const nameBytes = encoder.encode(name);
    const extra = new Uint8Array(5);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(8, method, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, nameBytes.length, true);
    local.setUint16(28, extra.length, true);
    const central = new DataView(new ArrayBuffer(46));
    central.setUint32(0, 0x02014b50, true);
    central.setUint16(10, method, true);
    central.setUint32(20, data.length, true);
    central.setUint32(24, data.length, true);
    central.setUint16(28, nameBytes.length, true);
    central.setUint32(42, offset, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, extra, data);
    directory.push(new Uint8Array(central.buffer), nameBytes);
    offset += 30 + nameBytes.length + extra.length + data.length;
  }
  const directorySize = directory.reduce((sum, part) => sum + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(10, Object.keys(files).length, true);
  end.setUint32(12, directorySize, true);
  end.setUint32(16, offset, true);
  return new Blob([...parts, ...directory, new Uint8Array(end.buffer)].map((part) => part.slice().buffer));
}

const manifest = (extra: Record<string, unknown> = {}) =>
  new TextEncoder().encode(JSON.stringify({ format: "stem-studio-player", version: 1, sourceName: "Mon morceau", stems: STEMS, ...extra }));
const audio = (byte: number) => new Uint8Array([byte, byte, byte]);

describe("song package", () => {
  it("returns each stem as a slice of the archive with the saved mix and tempo", async () => {
    const tempo = { bpm: 152, beatsPerBar: 4, source: "bass transcription", beats: [{ beatIndex: 0, timeSeconds: 0.6 }, { beatIndex: 1, timeSeconds: 1 }] };
    const state = { startMarkerSeconds: 12.5, masterVolume: 0.45, tracks: { drums: { volume: 0.4, muted: true, solo: false } } };
    const pkg = await readStemPackage(zip({
      "player.json": manifest({ tempo, state }),
      "vocals.m4a": audio(1),
      "drums.m4a": audio(2),
      "bass.m4a": audio(3),
      "other.m4a": audio(4),
    }));
    expect(pkg.sourceName).toBe("Mon morceau");
    expect([...new Uint8Array(await pkg.stems.bass.arrayBuffer())]).toEqual([3, 3, 3]);
    expect(pkg.stems.other.type).toBe("audio/mp4");
    expect(pkg.tempo).toEqual(tempo);
    expect(pkg.mix).toMatchObject({ startMarkerSeconds: 12.5, masterVolume: 0.45, tracks: { drums: { volume: 0.4, muted: true } } });
    expect(pkg.mix!.tracks.vocals).toEqual({ volume: 0.8, muted: false, solo: false });
  });

  it("explains archives it cannot play", async () => {
    await expect(readStemPackage(new Blob(["not a zip"]))).rejects.toThrow(/not a ZIP/);
    await expect(readStemPackage(zip({ "vocals.m4a": audio(1) }))).rejects.toThrow(/no player.json/);
    await expect(readStemPackage(zip({ "player.json": manifest(), "vocals.m4a": audio(1) }))).rejects.toThrow(/no drums stem/);
    await expect(readStemPackage(zip({ "player.json": manifest() }, 8))).rejects.toThrow(/compressed/);
  });

  it("drops a damaged tempo or mix instead of refusing the song", () => {
    const parsed = parseManifest({ format: "stem-studio-player", version: 1, stems: STEMS, tempo: { bpm: 900, beats: [] }, state: "x" });
    expect(parsed).toMatchObject({ sourceName: "Session", tempo: null, mix: null });
    expect(() => parseManifest({ format: "stem-studio-player", version: 2, stems: STEMS })).toThrow(/version 2/);
  });
});
