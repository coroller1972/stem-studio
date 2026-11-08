import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { save } from "@tauri-apps/plugin-dialog";
import type { PortableSessionState } from "../domain/types";
import { sessionBaseName } from "./sessionService";

/** The single-file song package read by the iPhone stem player (app/player.html). */
export interface PlayerPackage {
  path: string;
  tempoBpm: number | null;
  tempoSource: string | null;
}

export interface PlayerExportProgress {
  progress: number;
  message: string;
}

export class TauriPlayerExportService {
  chooseDestination(sourceName: string): Promise<string | null> {
    return save({
      title: "Export for the iPhone player",
      defaultPath: `${sessionBaseName(sourceName)}.stems.zip`,
      filters: [{ name: "iPhone song package", extensions: ["zip"] }],
    });
  }

  async export(
    projectPath: string,
    destinationPath: string,
    sourceName: string,
    mix: PortableSessionState,
    onProgress: (update: PlayerExportProgress) => void,
  ): Promise<PlayerPackage> {
    let unlisten: UnlistenFn | undefined;
    try {
      unlisten = await listen<{ type?: string; progress?: number; message?: string }>(
        "player-export-event",
        ({ payload }) => {
          if (payload.type === "export_progress" && typeof payload.message === "string") {
            onProgress({ progress: Number(payload.progress) || 0, message: payload.message });
          }
        },
      );
      return parsePlayerPackage(
        await invoke<unknown>("export_player_package", { projectPath, destinationPath, sourceName, mix }),
      );
    } finally {
      unlisten?.();
    }
  }
}

export function parsePlayerPackage(value: unknown): PlayerPackage {
  const result = value as Partial<PlayerPackage> | null;
  if (
    !result
    || typeof result.path !== "string"
    || !(result.tempoBpm === null || typeof result.tempoBpm === "number")
    || !(result.tempoSource === null || typeof result.tempoSource === "string")
  ) {
    throw new Error("The engine returned an invalid iPhone package.");
  }
  return result as PlayerPackage;
}

/** One line for the status toast once the package is written. */
export function describePlayerPackage(result: PlayerPackage): string {
  const fileName = result.path.split(/[\\/]/).pop() ?? result.path;
  const tempo = result.tempoSource
    ? `metronome from the ${result.tempoSource}`
    : "no tempo found, so no metronome";
  return `Exported ${fileName} for iPhone · ${tempo}`;
}
