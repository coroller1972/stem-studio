import { STEM_NAMES, type SeparationEvent, type StemPaths } from "../domain/types";

export function parseSeparationEvent(line: string): SeparationEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;

  let raw: unknown;
  try {
    raw = JSON.parse(trimmed);
  } catch {
    return null;
  }

  if (!isRecord(raw) || typeof raw.type !== "string") return null;

  if (raw.type === "progress") {
    if (typeof raw.progress !== "number" || typeof raw.message !== "string") return null;
    return {
      type: "progress",
      progress: Math.min(1, Math.max(0, raw.progress)),
      message: raw.message,
    };
  }

  if (raw.type === "completed" && isStemPaths(raw.stems)) {
    return { type: "completed", stems: raw.stems };
  }

  if (raw.type === "error" && typeof raw.message === "string") {
    return {
      type: "error",
      message: raw.message,
      ...(typeof raw.detail === "string" ? { detail: raw.detail } : {}),
    };
  }

  return null;
}

function isStemPaths(value: unknown): value is StemPaths {
  return (
    isRecord(value) &&
    STEM_NAMES.every((name) => typeof value[name] === "string" && value[name].length > 0)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

