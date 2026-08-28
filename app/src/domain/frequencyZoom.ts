export const SPECTRUM_ZOOM_LEVELS = [1, 2, 4, 8] as const;

export function nextSpectrumZoom(current: number, direction: -1 | 1): number {
  const index = SPECTRUM_ZOOM_LEVELS.findIndex((level) => level === current);
  const safeIndex = index < 0 ? 0 : index;
  return SPECTRUM_ZOOM_LEVELS[
    Math.min(SPECTRUM_ZOOM_LEVELS.length - 1, Math.max(0, safeIndex + direction))
  ]!;
}

export function centerScrollLeft(viewportWidth: number, contentWidth: number, playhead: number): number {
  return clampScrollLeft(playhead * contentWidth - viewportWidth / 2, viewportWidth, contentWidth);
}

export function followScrollLeft(
  currentLeft: number,
  viewportWidth: number,
  contentWidth: number,
  playhead: number,
): number {
  const playheadX = Math.min(1, Math.max(0, playhead)) * contentWidth;
  const leadingEdge = currentLeft + viewportWidth * 0.15;
  const trailingEdge = currentLeft + viewportWidth * 0.85;
  if (playheadX >= leadingEdge && playheadX <= trailingEdge) return currentLeft;
  return clampScrollLeft(playheadX - viewportWidth * 0.35, viewportWidth, contentWidth);
}

function clampScrollLeft(value: number, viewportWidth: number, contentWidth: number): number {
  return Math.min(Math.max(0, contentWidth - viewportWidth), Math.max(0, value));
}
