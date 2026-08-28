import type { TransportStatus } from "./types";

export interface TransportSnapshot {
  status: TransportStatus;
  currentTime: number;
  duration: number;
  startMarkerSeconds: number;
}

export type TransportAction =
  | { type: "play" }
  | { type: "pause" }
  | { type: "stop" }
  | { type: "seek"; seconds: number }
  | { type: "set-marker"; seconds: number }
  | { type: "play-from-marker" };

export function reduceTransport(
  snapshot: TransportSnapshot,
  action: TransportAction,
): TransportSnapshot {
  switch (action.type) {
    case "play":
      return { ...snapshot, status: "playing" };
    case "pause":
      return { ...snapshot, status: "paused" };
    case "stop":
      return { ...snapshot, status: "stopped", currentTime: snapshot.startMarkerSeconds };
    case "seek":
      return { ...snapshot, currentTime: clampTime(action.seconds, snapshot.duration) };
    case "set-marker":
      return {
        ...snapshot,
        startMarkerSeconds: clampTime(action.seconds, snapshot.duration),
      };
    case "play-from-marker":
      return {
        ...snapshot,
        status: "playing",
        currentTime: snapshot.startMarkerSeconds,
      };
  }
}

export function clampTime(seconds: number, duration: number): number {
  if (!Number.isFinite(seconds)) return 0;
  return Math.min(Math.max(0, duration), Math.max(0, seconds));
}

export function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remaining = safeSeconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining.toFixed(3).padStart(6, "0")}`;
}

