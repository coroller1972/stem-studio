import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import type { SeparationEvent, SeparationQuality, SeparationResult } from "../domain/types";
import { parseSeparationEvent } from "./sidecarEvents";

export interface SeparationService {
  chooseFile(): Promise<string | null>;
  separate(
    inputPath: string,
    quality: SeparationQuality,
    onEvent: (event: SeparationEvent) => void,
  ): Promise<SeparationResult>;
  cancel(): Promise<void>;
}

export class TauriSeparationService implements SeparationService {
  async chooseFile(): Promise<string | null> {
    const result = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "Audio", extensions: ["mp3", "wav"] }],
    });
    return typeof result === "string" ? result : null;
  }

  async separate(
    inputPath: string,
    quality: SeparationQuality,
    onEvent: (event: SeparationEvent) => void,
  ): Promise<SeparationResult> {
    let unlisten: UnlistenFn | undefined;
    try {
      unlisten = await listen<unknown>("separation-event", ({ payload }) => {
        const parsed = coerceEvent(payload);
        if (parsed) onEvent(parsed);
      });
      return await invoke<SeparationResult>("separate_audio", { inputPath, quality });
    } finally {
      unlisten?.();
    }
  }

  async cancel(): Promise<void> {
    await invoke("cancel_separation");
  }
}

function coerceEvent(payload: unknown): SeparationEvent | null {
  if (typeof payload === "string") return parseSeparationEvent(payload);
  try {
    return parseSeparationEvent(JSON.stringify(payload));
  } catch {
    return null;
  }
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
