import { useCallback, useEffect, useMemo, useRef } from "react";
import { AudioEngine } from "../audio/AudioEngine";
import type { SpectralStemName, StemPaths } from "../domain/types";
import { useProjectStore } from "../state/projectStore";

export function useAudioEngine() {
  const engineRef = useRef<AudioEngine | null>(null);
  engineRef.current ??= new AudioEngine();
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
    () => () => {
      void engineRef.current?.dispose();
    },
    [],
  );

  const load = useCallback(async (stems: StemPaths) => {
    const engine = engineRef.current!;
    const waveforms = await engine.load(stems);
    const state = useProjectStore.getState();
    engine.setTrackStates(state.tracks);
    engine.setMasterVolume(state.masterVolume);
    useProjectStore.getState().setReady(engine.duration, waveforms);
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
    await engine.play(from);
    state.setCurrentTime(from);
    state.setTransportStatus("playing");
  }, []);

  const playFromMarker = useCallback(async () => {
    const state = useProjectStore.getState();
    await engineRef.current!.play(state.startMarkerSeconds);
    state.setCurrentTime(state.startMarkerSeconds);
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

  return useMemo(
    () => ({ load, togglePlayback, playFromMarker, seek, getSpectrogram }),
    [load, togglePlayback, playFromMarker, seek, getSpectrogram],
  );
}
