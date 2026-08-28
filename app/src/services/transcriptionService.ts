import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { save } from "@tauri-apps/plugin-dialog";
import type {
  BassTranscription,
  BassTranscriptionEngine,
  BassTuning,
  DrumTranscription,
  TranscriptionEvent,
  TranscriptionFiles,
  TranscriptionTrack,
} from "../domain/types";

type ResultFor<T extends TranscriptionTrack> = T extends "bass"
  ? TranscriptionFiles<BassTranscription>
  : TranscriptionFiles<DrumTranscription>;

export class TauriTranscriptionService {
  async transcribe<T extends TranscriptionTrack>(
    projectPath: string,
    track: T,
    onEvent: (event: TranscriptionEvent) => void,
    bassTuning?: BassTuning,
    bassEngine?: BassTranscriptionEngine,
  ): Promise<ResultFor<T>> {
    let unlisten: UnlistenFn | undefined;
    try {
      unlisten = await listen<TranscriptionEvent>("transcription-event", ({ payload }) => onEvent(payload));
      return await invoke<ResultFor<T>>("transcribe_track", {
        projectPath,
        track,
        bassTuning,
        bassEngine,
      });
    } finally {
      unlisten?.();
    }
  }

  async requantize<T extends TranscriptionTrack>(
    projectPath: string,
    track: T,
    bpm: number,
    firstMeasureSeconds: number,
    onEvent: (event: TranscriptionEvent) => void,
  ): Promise<ResultFor<T>> {
    let unlisten: UnlistenFn | undefined;
    try {
      unlisten = await listen<TranscriptionEvent>("transcription-event", ({ payload }) => onEvent(payload));
      return await invoke<ResultFor<T>>("requantize_transcription", {
        projectPath,
        track,
        bpm,
        firstMeasureSeconds,
      });
    } finally {
      unlisten?.();
    }
  }

  async exportFile(
    sourcePath: string,
    suggestedName: string,
    extension: "mid" | "musicxml",
  ): Promise<string | null> {
    const destinationPath = await save({
      title: `Export ${suggestedName}`,
      defaultPath: suggestedName,
      filters: [{ name: extension === "mid" ? "MIDI" : "MusicXML", extensions: [extension] }],
    });
    if (!destinationPath) return null;
    await invoke("export_transcription_file", { sourcePath, destinationPath });
    return destinationPath;
  }
}
