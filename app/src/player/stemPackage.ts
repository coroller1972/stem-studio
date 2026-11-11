import { clampVolume, createDefaultTracks } from "../domain/mixer";
import { parseMetronomeTempo, type MetronomeTempo } from "../domain/metronomeTempo";
import { STEM_NAMES, type StemName, type StemState } from "../domain/types";

/** Written by scripts/export_iphone_package.py. */
export const PACKAGE_FORMAT = "stem-studio-player";
const PACKAGE_VERSION = 1;
const MANIFEST_NAME = "player.json";
const MAX_MANIFEST_BYTES = 4 * 1024 * 1024;

export type PlayerTempo = MetronomeTempo;

export interface PackageMix {
  startMarkerSeconds: number;
  masterVolume: number | null;
  tracks: Record<StemName, StemState>;
}

export interface StemPackage {
  sourceName: string;
  /** Slices of the picked file: nothing is copied until the stem is decoded. */
  stems: Record<StemName, Blob>;
  mix: PackageMix | null;
  tempo: PlayerTempo | null;
}

interface ZipEntry {
  name: string;
  method: number;
  size: number;
  localHeaderOffset: number;
}

export function isStemPackageName(fileName: string): boolean {
  return /\.zip$/iu.test(fileName);
}

export async function readStemPackage(file: Blob): Promise<StemPackage> {
  const entries = await readZipDirectory(file);
  const manifestEntry = entries.get(MANIFEST_NAME);
  if (!manifestEntry) throw new Error("This archive is not a Stem Studio song package (no player.json).");
  if (manifestEntry.size > MAX_MANIFEST_BYTES) throw new Error("The song package manifest is unexpectedly large.");
  const manifestBlob = await entryBlob(file, manifestEntry);
  let manifest: unknown;
  try {
    manifest = JSON.parse(new TextDecoder().decode(await manifestBlob.arrayBuffer()));
  } catch {
    throw new Error("The song package manifest is not valid JSON.");
  }
  const parsed = parseManifest(manifest);
  const stems = {} as Record<StemName, Blob>;
  for (const name of STEM_NAMES) {
    const entry = entries.get(parsed.stemFiles[name]);
    if (!entry) throw new Error(`The song package has no ${name} stem.`);
    stems[name] = await entryBlob(file, entry);
  }
  return { sourceName: parsed.sourceName, stems, mix: parsed.mix, tempo: parsed.tempo };
}

export function parseManifest(value: unknown): Omit<StemPackage, "stems"> & { stemFiles: Record<StemName, string> } {
  const manifest = record(value);
  if (!manifest || manifest.format !== PACKAGE_FORMAT) {
    throw new Error("This archive is not a Stem Studio song package.");
  }
  if (manifest.version !== PACKAGE_VERSION) {
    throw new Error(`Song package version ${String(manifest.version)} is not supported by this player.`);
  }
  const stems = record(manifest.stems);
  if (!stems || !STEM_NAMES.every((name) => typeof stems[name] === "string")) {
    throw new Error("The song package does not list its four stems.");
  }
  const sourceName = typeof manifest.sourceName === "string" && manifest.sourceName.trim()
    ? manifest.sourceName.trim()
    : "Session";
  return {
    sourceName,
    stemFiles: stems as Record<StemName, string>,
    // The mix and the tempo are conveniences: a damaged one is dropped, not fatal.
    mix: parseMix(manifest.state),
    tempo: parseMetronomeTempo(manifest.tempo, "package"),
  };
}

function parseMix(value: unknown): PackageMix | null {
  const state = record(value);
  if (!state) return null;
  const tracks = createDefaultTracks();
  const savedTracks = record(state.tracks);
  for (const name of STEM_NAMES) {
    const track = record(savedTracks?.[name]);
    if (!track) continue;
    tracks[name] = {
      volume: isUnit(track.volume) ? track.volume : tracks[name].volume,
      muted: track.muted === true,
      solo: track.solo === true,
    };
  }
  return {
    startMarkerSeconds: isFiniteNumber(state.startMarkerSeconds) ? Math.max(0, state.startMarkerSeconds) : 0,
    masterVolume: isUnit(state.masterVolume) ? clampVolume(state.masterVolume) : null,
    tracks,
  };
}

/** Reads the central directory of a ZIP archive without loading its contents. */
async function readZipDirectory(file: Blob): Promise<Map<string, ZipEntry>> {
  const tailStart = Math.max(0, file.size - 22 - 0xffff);
  const tail = new DataView(await file.slice(tailStart).arrayBuffer());
  let end = -1;
  for (let offset = tail.byteLength - 22; offset >= 0; offset -= 1) {
    if (tail.getUint32(offset, true) === 0x06054b50) {
      end = offset;
      break;
    }
  }
  if (end < 0) throw new Error("This file is not a ZIP archive.");
  const entryCount = tail.getUint16(end + 10, true);
  const directorySize = tail.getUint32(end + 12, true);
  const directoryOffset = tail.getUint32(end + 16, true);
  if (directoryOffset + directorySize > file.size) throw new Error("The song package is truncated.");

  const directory = new DataView(await file.slice(directoryOffset, directoryOffset + directorySize).arrayBuffer());
  const decoder = new TextDecoder();
  const entries = new Map<string, ZipEntry>();
  let offset = 0;
  for (let index = 0; index < entryCount; index += 1) {
    if (offset + 46 > directory.byteLength || directory.getUint32(offset, true) !== 0x02014b50) {
      throw new Error("The song package directory is damaged.");
    }
    const nameLength = directory.getUint16(offset + 28, true);
    const extraLength = directory.getUint16(offset + 30, true);
    const commentLength = directory.getUint16(offset + 32, true);
    const name = decoder.decode(new Uint8Array(directory.buffer, directory.byteOffset + offset + 46, nameLength));
    entries.set(name, {
      name,
      method: directory.getUint16(offset + 10, true),
      size: directory.getUint32(offset + 20, true),
      localHeaderOffset: directory.getUint32(offset + 42, true),
    });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function entryBlob(file: Blob, entry: ZipEntry): Promise<Blob> {
  if (entry.method !== 0) {
    throw new Error(`${entry.name} is compressed. Export the song again with scripts/export_iphone_package.py.`);
  }
  const header = new DataView(await file.slice(entry.localHeaderOffset, entry.localHeaderOffset + 30).arrayBuffer());
  if (header.byteLength < 30 || header.getUint32(0, true) !== 0x04034b50) {
    throw new Error("The song package is damaged.");
  }
  const start = entry.localHeaderOffset + 30 + header.getUint16(26, true) + header.getUint16(28, true);
  if (start + entry.size > file.size) throw new Error("The song package is truncated.");
  return file.slice(start, start + entry.size, entry.name.endsWith(".m4a") ? "audio/mp4" : "");
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isUnit(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}
