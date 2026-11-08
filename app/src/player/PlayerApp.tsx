import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FolderOpen, Music2, Timer } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { Timeline } from "../components/Timeline";
import { Transport } from "../components/Transport";
import { useAudioEngine } from "../hooks/useAudioEngine";
import { createDefaultTracks } from "../domain/mixer";
import { STEM_NAMES, type StemName, type StemPaths } from "../domain/types";
import { useProjectStore } from "../state/projectStore";
import { ClickTrack } from "./clickTrack";
import { buildMetronomeGrid } from "./metronome";
import {
  MetronomePanel,
  loadMetronomeSettings,
  saveMetronomeSettings,
  type MetronomeSettings,
} from "./MetronomePanel";
import { assignStemFiles } from "./stemFiles";
import { isStemPackageName, parseManifest, readStemPackage, type PackageMix, type PlayerTempo } from "./stemPackage";

interface PickedSong {
  sourceName: string;
  stems: Record<StemName, Blob>;
  mix: PackageMix | null;
  tempo: PlayerTempo | null;
}

/** Replays a song picked from the iPhone's Files app; nothing leaves the device. */
export function PlayerApp() {
  const clickTrackRef = useRef<ClickTrack | null>(null);
  clickTrackRef.current ??= new ClickTrack();
  const clickTrack = clickTrackRef.current;
  const audio = useAudioEngine({
    leadInSeconds: (from) => clickTrack.leadInSeconds(from),
    playbackListener: clickTrack,
  });
  const inputRef = useRef<HTMLInputElement>(null);
  const loadVersion = useRef(0);
  const [pickError, setPickError] = useState<string | null>(null);
  const [decodedMegabytes, setDecodedMegabytes] = useState<number | null>(null);
  const [tempo, setTempo] = useState<PlayerTempo | null>(null);
  const [metronome, setMetronome] = useState<MetronomeSettings>(loadMetronomeSettings);
  const state = useProjectStore(useShallow((store) => ({
    status: store.status,
    errorMessage: store.errorMessage,
    sourceName: store.source?.name ?? null,
    duration: store.duration,
    startMarkerSeconds: store.startMarkerSeconds,
    masterVolume: store.masterVolume,
    tracks: store.tracks,
    waveforms: store.waveforms,
    transcriptions: store.transcriptions,
    transportStatus: store.transportStatus,
    setTrack: store.setTrack,
    setStartMarker: store.setStartMarker,
    setMasterVolume: store.setMasterVolume,
  })));

  const grid = useMemo(() => (tempo ? buildMetronomeGrid(tempo.beats, tempo.beatsPerBar) : null), [tempo]);

  useEffect(() => clickTrack.setGrid(grid), [clickTrack, grid]);
  useEffect(() => {
    clickTrack.setCountInBars(metronome.countInBars);
    clickTrack.setSongClicks(metronome.songClicks);
    clickTrack.setVolume(metronome.volume);
    saveMetronomeSettings(metronome);
  }, [clickTrack, metronome]);

  const loadSong = useCallback(async (song: PickedSong, version: number) => {
    setTempo(song.tempo);
    const store = useProjectStore.getState();
    const urls = Object.fromEntries(
      STEM_NAMES.map((name) => [name, URL.createObjectURL(song.stems[name])]),
    ) as StemPaths;
    store.restoreSession("", "", song.sourceName, urls, {
      currentTimeSeconds: song.mix?.startMarkerSeconds ?? 0,
      startMarkerSeconds: song.mix?.startMarkerSeconds ?? 0,
      masterVolume: song.mix?.masterVolume ?? store.masterVolume,
      tracks: song.mix?.tracks ?? createDefaultTracks(),
    }, { bass: null, drums: null }, "standard");
    try {
      await audio.load(urls);
      if (version === loadVersion.current) setDecodedMegabytes(audio.decodedBytes() / 1024 ** 2);
    } catch (error) {
      if (version !== loadVersion.current) return;
      useProjectStore.getState().setError(error instanceof Error ? error.message : String(error));
    } finally {
      // The decoded buffers no longer need the files.
      Object.values(urls).forEach((url) => URL.revokeObjectURL(url));
    }
  }, [audio]);

  const loadFiles = useCallback(async (picked: File[]) => {
    const version = ++loadVersion.current;
    setPickError(null);
    setDecodedMegabytes(null);
    let song: PickedSong;
    const packageFile = picked.find((file) => isStemPackageName(file.name));
    if (packageFile) {
      if (picked.length > 1) {
        setPickError("Pick one song package, or the four stems of a song.");
        return;
      }
      try {
        song = await readStemPackage(packageFile);
      } catch (error) {
        if (version === loadVersion.current) setPickError(error instanceof Error ? error.message : String(error));
        return;
      }
    } else {
      const assignment = assignStemFiles(picked);
      if (!assignment.ok) {
        setPickError(assignment.message);
        return;
      }
      song = { sourceName: assignment.sourceName, stems: assignment.files, mix: null, tempo: null };
      // Files can unzip a package when it is tapped: its player.json, picked
      // with the stems, still brings the song's name, mix and tempo.
      const manifestFile = picked.find((file) => /\.json$/iu.test(file.name));
      if (manifestFile) {
        try {
          const manifest = parseManifest(JSON.parse(await manifestFile.text()));
          song = { ...song, sourceName: manifest.sourceName, mix: manifest.mix, tempo: manifest.tempo };
        } catch {
          // Without a readable manifest the stems still play, without a metronome.
        }
      }
    }
    if (version !== loadVersion.current) return;
    audio.clear();
    await loadSong(song, version);
  }, [audio, loadSong]);

  const chooseFiles = () => inputRef.current?.click();

  const changeSong = () => {
    loadVersion.current += 1;
    audio.clear();
    useProjectStore.getState().reset();
    setDecodedMegabytes(null);
    setTempo(null);
    chooseFiles();
  };

  useEffect(() => () => useProjectStore.getState().reset(), []);

  return (
    <div className="player-shell">
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        multiple
        accept=".zip,application/zip,audio/*,.m4a,.wav,.mp3"
        onChange={(event) => {
          const picked = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (picked.length) void loadFiles(picked);
        }}
      />
      {state.status === "ready" ? (
        <>
          <div className="player-top">
            <header className="player-header">
              <div className="player-title">
                <strong>{state.sourceName}</strong>
                {decodedMegabytes !== null ? (
                  <span>{Math.round(decodedMegabytes)} MB of decoded audio</span>
                ) : null}
              </div>
              <div className="player-header-actions">
                {grid && tempo ? (
                  <span className="metronome-tempo" title={`From the ${tempo.source}`}>
                    <Timer size={14} aria-hidden="true" /> {Math.round(grid.bpm)} BPM
                  </span>
                ) : null}
                <button type="button" className="ghost-button" onClick={changeSong}>
                  <FolderOpen size={14} /> Change
                </button>
              </div>
            </header>
            {grid ? (
              <MetronomePanel settings={metronome} onChange={setMetronome} />
            ) : (
              <p className="metronome-missing">
                No tempo in these files, so no metronome. Export the song with
                scripts/export_iphone_package.py and pick the .stems.zip.
              </p>
            )}
          </div>
          <main className="player-main">
            <Timeline
              duration={state.duration}
              startMarkerSeconds={state.startMarkerSeconds}
              tracks={state.tracks}
              waveforms={state.waveforms}
              transcriptions={state.transcriptions}
              onTrackChange={state.setTrack}
              onSeek={(seconds) => void audio.seek(seconds)}
              onMarkerChange={state.setStartMarker}
            />
          </main>
          <Transport
            status={state.transportStatus}
            duration={state.duration}
            marker={state.startMarkerSeconds}
            masterVolume={state.masterVolume}
            onToggle={() => void audio.togglePlayback()}
            onReturnToMarker={() => void audio.seek(state.startMarkerSeconds)}
            onPlayFromMarker={() => void audio.playFromMarker()}
            onSetMarker={() => state.setStartMarker(useProjectStore.getState().currentTime)}
            onMasterVolumeChange={state.setMasterVolume}
          />
        </>
      ) : (
        <main className="player-empty">
          <Music2 size={34} aria-hidden="true" />
          <h1>Stem Player</h1>
          {state.status === "loading" ? (
            <p role="status">Decoding the four stems…</p>
          ) : (
            <>
              <p>Pick a song package (.stems.zip) exported from Stem Studio, or the four stems of a song.</p>
              <button type="button" className="primary-button" onClick={chooseFiles}>
                <FolderOpen size={16} /> Choose a song
              </button>
            </>
          )}
          {pickError ?? (state.status === "error" ? state.errorMessage : null) ? (
            <p className="player-error" role="alert">
              {pickError ?? state.errorMessage}
            </p>
          ) : null}
        </main>
      )}
    </div>
  );
}
