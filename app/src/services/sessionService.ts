import { invoke } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";
import type {
  PortableSessionState,
  RestoredSession,
  SavedSession,
  SeparationQuality,
} from "../domain/types";
import { parseRestoredSession } from "../domain/sessionValidation";

export class TauriSessionService {
  chooseSessionPath(sourceName: string): Promise<string | null> {
    return save({
      title: "Save Stem Studio session",
      defaultPath: `${sessionBaseName(sourceName)}.stemstudio`,
      filters: [{ name: "Stem Studio session", extensions: ["stemstudio"] }],
    });
  }

  chooseManifest(): Promise<string | null> {
    return open({
      directory: false,
      multiple: false,
      title: "Open a Stem Studio session",
      filters: [{ name: "Stem Studio session", extensions: ["json"] }],
    });
  }

  save(
    projectPath: string,
    sessionPath: string,
    sourceName: string,
    qualityProfile: SeparationQuality,
    state: PortableSessionState,
  ): Promise<SavedSession> {
    return invoke<SavedSession>("save_session", {
      projectPath,
      sessionPath,
      sourceName,
      qualityProfile,
      state,
    });
  }

  async load(manifestPath: string): Promise<RestoredSession> {
    return parseRestoredSession(await invoke<unknown>("load_session", { manifestPath }));
  }
}

function sessionBaseName(sourceName: string): string {
  const fileName = sourceName.split(/[\\/]/).pop() || "session";
  const withoutExtension = fileName.replace(/\.[^.]+$/, "");
  const sanitized = withoutExtension.replace(/[^\p{L}\p{N} _-]+/gu, "-").replace(/^[ _-]+|[ _-]+$/g, "");
  return sanitized.slice(0, 80) || "session";
}
