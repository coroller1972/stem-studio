import { invoke } from "@tauri-apps/api/core";
import { parseMetronomeTempo, type MetronomeTempo } from "../domain/metronomeTempo";

/**
 * Runs the engine's beat tracker on the project's four stems, as the iPhone
 * export does. The engine caches the result in the project (tempo.json), so
 * only the first request for a song takes a few seconds.
 */
export class TauriTempoService {
  async detect(projectPath: string): Promise<MetronomeTempo | null> {
    return parseDetectedTempo(await invoke<unknown>("detect_tempo", { projectPath }));
  }
}

/** null when the engine found no steady tempo. */
export function parseDetectedTempo(value: unknown): MetronomeTempo | null {
  if (value === null || value === undefined) return null;
  const tempo = parseMetronomeTempo(value, "beat tracker");
  if (!tempo) throw new Error("The engine returned an invalid tempo.");
  return tempo;
}
