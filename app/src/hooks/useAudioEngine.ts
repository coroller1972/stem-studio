import { useCallback, useEffect, useMemo, useRef } from "react";
import { AudioEngine, type PlaybackListener } from "../audio/AudioEngine";
import type { SpectralStemName, StemPaths } from "../domain/types";
import { useProjectStore } from "../state/projectStore";

export interface AudioEngineOptions {
  /** Silence before playback started by the user, such as a count-in. Seeking never waits. */
  leadInSeconds?: (fromSeconds: number) => number;
  playbackListener?: PlaybackListener;
}

export function useAudioEngine(options: AudioEngineOptions = {}) {
  const engineRef = useRef<AudioEngine | null>(null);
  engineRef.current ??= new AudioEngine();
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });
  const tracks = useProjectStore((state) => state.tracks);
  const masterVolume = useProjectStore((state) => state.masterVolume);
  const transportStatus = useProjectStore((state) => state.transportStatus);

  useEffect(() => {
    engineRef.current?.setTrackStates(tracks);
  }, [tracks]);

  useEffect(() => {
    engineRef.current?.setMasterVolume(masterVolume);
  }, [masterVolume]);

  useEffect(() => {
    if (transportStatus !== "playing") return;
    let frame = 0;
    const update = () => {
      const engine = engineRef.current;
      if (!engine) return;
      useProjectStore.getState().setCurrentTime(engine.currentTime);
      if (!engine.isPlaying) {
        useProjectStore.getState().setTransportStatus("stopped");
        return;
      }
      frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [transportStatus]);

  useEffect(
    () =>
      engineRef.current!.addPlaybackListener({
        start: (clock) => optionsRef.current.playbackListener?.start(clock),
        stop: () => optionsRef.current.playbackListener?.stop(),
      }),
    [],
  );

  useEffect(
    () => () => {
      void engineRef.current?.dispose();
    },
    [],
  );

  const load = useCallback(async (stems: StemPaths, signal?: AbortSignal) => {
    const engine = engineRef.current!;
    signal?.throwIfAborted();
    const waveforms = await engine.load(stems);
    signal?.throwIfAborted();
    const state = useProjectStore.getState();
    engine.setTrackStates(state.tracks);
    engine.setMasterVolume(state.masterVolume);
    useProjectStore.getState().setReady(engine.duration, waveforms);
  }, []);

  const clear = useCallback(() => {
    engineRef.current!.clear();
    useProjectStore.getState().setTransportStatus("stopped");
  }, []);

  const togglePlayback = useCallback(async () => {
    const engine = engineRef.current!;
    const state = useProjectStore.getState();
    if (state.transportStatus === "playing") {
      state.setCurrentTime(engine.pause());
      state.setTransportStatus("paused");
      return;
    }
    const from = state.transportStatus === "stopped" ? state.startMarkerSeconds : state.currentTime;
    await engine.play(from, optionsRef.current.leadInSeconds?.(from) ?? 0);
    if (!engine.isPlaying) return;
    state.setCurrentTime(engine.currentTime);
    state.setTransportStatus("playing");
  }, []);

  const playFromMarker = useCallback(async () => {
    const state = useProjectStore.getState();
    const from = state.startMarkerSeconds;
    await engineRef.current!.play(from, optionsRef.current.leadInSeconds?.(from) ?? 0);
    if (!engineRef.current!.isPlaying) return;
    state.setCurrentTime(engineRef.current!.currentTime);
    state.setTransportStatus("playing");
  }, []);

  const seek = useCallback(async (seconds: number) => {
    if (engineRef.current!.duration === 0 && useProjectStore.getState().duration > 0) {
      useProjectStore.getState().setCurrentTime(seconds);
      return;
    }
    const next = await engineRef.current!.seek(seconds);
    useProjectStore.getState().setCurrentTime(next);
  }, []);

  const getSpectrogram = useCallback((stem: SpectralStemName) => {
    return engineRef.current!.getSpectrogram(stem);
  }, []);

  const decodedBytes = useCallback(() => engineRef.current!.decodedBytes, []);

  return useMemo(
    () => ({ load, clear, togglePlayback, playFromMarker, seek, getSpectrogram, decodedBytes }),
    [load, clear, togglePlayback, playFromMarker, seek, getSpectrogram, decodedBytes],
  );
}
