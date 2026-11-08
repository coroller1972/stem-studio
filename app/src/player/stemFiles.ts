import { STEM_NAMES, type StemName } from "../domain/types";

const STEM_KEYWORDS: Record<string, StemName> = {
  vocals: "vocals",
  vocal: "vocals",
  voix: "vocals",
  drums: "drums",
  drum: "drums",
  batterie: "drums",
  bass: "bass",
  basse: "bass",
  other: "other",
  autre: "other",
  autres: "other",
};

export type StemFileAssignment<T extends { name: string }> =
  | { ok: true; sourceName: string; files: Record<StemName, T> }
  | { ok: false; message: string };

/**
 * Pairs picked files with the four stems from their names. The last stem word
 * wins, so a song titled "All About That Bass - vocals" still maps to vocals.
 */
export function assignStemFiles<T extends { name: string }>(files: readonly T[]): StemFileAssignment<T> {
  const assigned: Partial<Record<StemName, T>> = {};
  for (const file of files) {
    const stem = stemFromFileName(file.name);
    if (!stem) continue;
    if (assigned[stem]) return { ok: false, message: `Two files look like the ${stem} stem.` };
    assigned[stem] = file;
  }
  const missing = STEM_NAMES.filter((name) => !assigned[name]);
  if (missing.length) {
    return {
      ok: false,
      message: `Missing ${missing.join(", ")}. Pick four files named with vocals, drums, bass and other.`,
    };
  }
  return { ok: true, sourceName: sharedSourceName(files.map((file) => file.name)), files: assigned as Record<StemName, T> };
}

export function stemFromFileName(fileName: string): StemName | null {
  const words = withoutExtension(fileName).toLowerCase().split(/[^\p{L}]+/u);
  for (let index = words.length - 1; index >= 0; index -= 1) {
    const stem = STEM_KEYWORDS[words[index]!];
    if (stem) return stem;
  }
  return null;
}

function sharedSourceName(fileNames: string[]): string {
  const names = fileNames.map(withoutExtension);
  let prefix = names[0] ?? "";
  for (const name of names.slice(1)) {
    while (!name.startsWith(prefix)) prefix = prefix.slice(0, -1);
  }
  const trimmed = prefix.replace(/[\s._-]+$/u, "");
  return trimmed || "Session";
}

function withoutExtension(fileName: string): string {
  return fileName.replace(/\.[^.]+$/u, "");
}
