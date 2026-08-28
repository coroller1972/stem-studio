import { describe, expect, it } from "vitest";
import { resolveTransportKeyboardShortcut } from "./keyboardShortcuts";

const event = (code: string, overrides = {}) => ({
  code,
  altKey: false,
  ctrlKey: false,
  metaKey: false,
  ...overrides,
});

describe("transport keyboard shortcuts", () => {
  it("moves one second in the requested directions", () => {
    expect(resolveTransportKeyboardShortcut(event("ArrowLeft"))).toEqual({
      type: "seek-relative",
      deltaSeconds: -1,
    });
    expect(resolveTransportKeyboardShortcut(event("ArrowRight"))).toEqual({
      type: "seek-relative",
      deltaSeconds: 1,
    });
  });

  it("returns to the marker with B", () => {
    expect(resolveTransportKeyboardShortcut(event("KeyB"))).toEqual({
      type: "return-to-marker",
    });
  });

  it("keeps the existing space shortcut and ignores modified shortcuts", () => {
    expect(resolveTransportKeyboardShortcut(event("Space"))).toEqual({
      type: "toggle-playback",
    });
    expect(resolveTransportKeyboardShortcut(event("KeyB", { metaKey: true }))).toBeNull();
    expect(resolveTransportKeyboardShortcut(event("ArrowLeft", { altKey: true }))).toBeNull();
  });
});
