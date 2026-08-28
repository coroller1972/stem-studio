export type TransportKeyboardShortcut =
  | { type: "toggle-playback" }
  | { type: "seek-relative"; deltaSeconds: number }
  | { type: "return-to-marker" };

interface KeyboardShortcutEvent {
  code: string;
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
}

export function resolveTransportKeyboardShortcut(
  event: KeyboardShortcutEvent,
): TransportKeyboardShortcut | null {
  if (event.altKey || event.ctrlKey || event.metaKey) return null;

  switch (event.code) {
    case "Space":
      return { type: "toggle-playback" };
    case "ArrowLeft":
      return { type: "seek-relative", deltaSeconds: -1 };
    case "ArrowRight":
      return { type: "seek-relative", deltaSeconds: 1 };
    case "KeyB":
      return { type: "return-to-marker" };
    default:
      return null;
  }
}
