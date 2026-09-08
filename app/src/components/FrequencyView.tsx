import { Activity, LoaderCircle, ZoomIn, ZoomOut } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { midiNoteName, spectrogramRange } from "../audio/spectrogram";
import {
  centerScrollLeft,
  followScrollLeft,
  nextSpectrumZoom,
  SPECTRUM_ZOOM_LEVELS,
} from "../domain/frequencyZoom";
import {
  SPECTRAL_STEM_NAMES,
  type SpectralStemName,
  type SpectrogramData,
} from "../domain/types";

import { useProjectStore } from "../state/projectStore";

interface FrequencyViewProps {
  duration: number;
  followPlayback: boolean;
  selectedStem: SpectralStemName;
  onStemChange: (stem: SpectralStemName) => void;
  onSeek: (seconds: number) => void;
  loadSpectrogram: (stem: SpectralStemName) => Promise<SpectrogramData>;
}

export function FrequencyView({
  duration,
  followPlayback,
  selectedStem,
  onStemChange,
  onSeek,
  loadSpectrogram,
}: FrequencyViewProps) {
  const currentTime = useProjectStore((state) => state.currentTime);
  const [results, setResults] = useState<Partial<Record<SpectralStemName, SpectrogramData>>>({});
  const [loadingStem, setLoadingStem] = useState<SpectralStemName | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ time: number; midi: number; x: number; y: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousZoom = useRef(zoom);
  const data = results[selectedStem];
  const visibleRange = data ?? spectrogramRange(selectedStem);
  const ticks = useMemo(() => createTicks(duration), [duration]);
  const pitchTicks = useMemo(
    () => createPitchTicks(visibleRange.minMidi, visibleRange.maxMidi),
    [visibleRange.minMidi, visibleRange.maxMidi],
  );

  useEffect(() => {
    if (results[selectedStem]) return;
    let active = true;
    setLoadingStem(selectedStem);
    setError(null);
    void loadSpectrogram(selectedStem)
      .then((result) => {
        if (!active) return;
        setResults((current) => ({ ...current, [selectedStem]: result }));
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (active) setLoadingStem(null);
      });
    return () => {
      active = false;
    };
  }, [loadSpectrogram, results, selectedStem]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    canvas.width = data.width;
    canvas.height = data.height;
    const context = canvas.getContext("2d");
    if (!context) return;
    const image = context.createImageData(data.width, data.height);
    for (let column = 0; column < data.width; column += 1) {
      for (let row = 0; row < data.height; row += 1) {
        const [red, green, blue] = spectralColor(data.values[column * data.height + row]! / 255);
        const pixel = (row * data.width + column) * 4;
        image.data[pixel] = red;
        image.data[pixel + 1] = green;
        image.data[pixel + 2] = blue;
        image.data[pixel + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
  }, [data]);

  useLayoutEffect(() => {
    if (previousZoom.current === zoom) return;
    previousZoom.current = zoom;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const playhead = duration > 0 ? currentTime / duration : 0;
    scroll.scrollLeft = centerScrollLeft(scroll.clientWidth, scroll.scrollWidth, playhead);
  }, [currentTime, duration, zoom]);

  useEffect(() => {
    if (!followPlayback || zoom === 1) return;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const playhead = duration > 0 ? currentTime / duration : 0;
    scroll.scrollLeft = followScrollLeft(
      scroll.scrollLeft,
      scroll.clientWidth,
      scroll.scrollWidth,
      playhead,
    );
  }, [currentTime, duration, followPlayback, zoom]);

  const pointerPosition = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = plotRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    const { minMidi, maxMidi } = visibleRange;
    return {
      time: x * duration,
      midi: Math.round(maxMidi - y * (maxMidi - minMidi)),
      x: x * 100,
      y: y * 100,
    };
  };

  return (
    <section className="frequency-view" aria-label="Frequency view">
      <header className="frequency-header">
        <div>
          <h2>Frequency view</h2>
          <p>Pitch-aligned spectrogram · {midiNoteName(visibleRange.minMidi)}–{midiNoteName(visibleRange.maxMidi)}</p>
        </div>
        <div className="frequency-tools">
          <div className="stem-spectrum-selector" role="group" aria-label="Stem to analyze">
            {SPECTRAL_STEM_NAMES.map((stem) => (
              <button
                type="button"
                key={stem}
                className={stem === selectedStem ? "is-active" : ""}
                aria-pressed={stem === selectedStem}
                onClick={() => onStemChange(stem)}
              >
                {stemLabel(stem)}
              </button>
            ))}
          </div>
          <div className="spectrum-zoom" role="group" aria-label="Timeline zoom">
            <button
              type="button"
              aria-label="Zoom out"
              disabled={zoom === SPECTRUM_ZOOM_LEVELS[0]}
              onClick={() => setZoom((current) => nextSpectrumZoom(current, -1))}
            ><ZoomOut size={14} /></button>
            <button
              type="button"
              className="spectrum-zoom-value"
              aria-label={`Reset zoom, currently ${zoom}×`}
              disabled={zoom === 1}
              onClick={() => setZoom(1)}
            >{zoom}×</button>
            <button
              type="button"
              aria-label="Zoom in"
              disabled={zoom === SPECTRUM_ZOOM_LEVELS.at(-1)}
              onClick={() => setZoom((current) => nextSpectrumZoom(current, 1))}
            ><ZoomIn size={14} /></button>
          </div>
        </div>
      </header>
      <div className="spectrogram-chart">
        <div className="pitch-axis-title">NOTE</div>
        <div className="pitch-axis" aria-hidden="true">
          {pitchTicks.map((tick) => (
            <span key={tick.midi} style={{ top: `${tick.percent}%` }}>{midiNoteName(tick.midi)}</span>
          ))}
        </div>
        <div className="spectrogram-scroll" ref={scrollRef}>
          <div className="spectrogram-scroll-content" style={{ width: `${zoom * 100}%` }}>
            <div className="spectrum-time-ruler">
              {ticks.map((tick) => (
                <span key={tick.seconds} style={{ left: `${tick.percent}%` }}>{formatRulerTime(tick.seconds)}</span>
              ))}
            </div>
            <div
              className="spectrogram-plot"
              ref={plotRef}
              onPointerMove={(event) => setHover(pointerPosition(event))}
              onPointerLeave={() => setHover(null)}
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                const position = pointerPosition(event);
                if (position) onSeek(position.time);
              }}
              title="Click to seek"
            >
              <canvas ref={canvasRef} aria-label={`${stemLabel(selectedStem)} musical spectrogram`} />
              {pitchTicks.map((tick) => (
                <i className="spectrogram-pitch-line" key={tick.midi} style={{ top: `${tick.percent}%` }} />
              ))}
              {ticks.map((tick) => (
                <i className="spectrogram-time-line" key={tick.seconds} style={{ left: `${tick.percent}%` }} />
              ))}
              <div className="spectrum-playhead" style={{ left: `${toPercent(currentTime, duration)}%` }}><span /></div>
              {hover ? (
                <>
                  <div className="spectrum-hover-x" style={{ left: `${hover.x}%` }} />
                  <div className="spectrum-hover-y" style={{ top: `${hover.y}%` }} />
                  <output
                    className={`spectrum-tooltip${hover.x > 78 ? " align-right" : ""}${hover.y < 16 ? " align-bottom" : ""}`}
                    style={{ left: `${hover.x}%`, top: `${hover.y}%` }}
                  >
                    <strong>{midiNoteName(hover.midi)}</strong>
                    <span>{formatPreciseTime(hover.time)}</span>
                  </output>
                </>
              ) : null}
              {!data && loadingStem === selectedStem ? (
                <div className="spectrogram-state" role="status">
                  <LoaderCircle className="spin" size={22} />
                  <strong>Analyzing {selectedStem} frequencies…</strong>
                  <span>The result is cached for this session.</span>
                </div>
              ) : null}
              {!data && error ? (
                <div className="spectrogram-state error" role="alert">
                  <Activity size={22} />
                  <strong>Frequency analysis unavailable</strong>
                  <span>{error}</span>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function createPitchTicks(minMidi: number, maxMidi: number) {
  const ticks = [{ midi: minMidi, percent: 100 }];
  for (let midi = 24; midi <= maxMidi; midi += 12) {
    if (midi > minMidi) ticks.push({ midi, percent: ((maxMidi - midi) / (maxMidi - minMidi)) * 100 });
  }
  return ticks.reverse();
}

function createTicks(duration: number) {
  const roughStep = duration / 8;
  const steps = [5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((candidate) => candidate >= roughStep) ?? 600;
  const ticks = [];
  for (let seconds = 0; seconds <= duration; seconds += step) {
    ticks.push({ seconds, percent: toPercent(seconds, duration) });
  }
  return ticks;
}

function spectralColor(value: number): [number, number, number] {
  const stops: Array<[number, number, number, number]> = [
    [0, 10, 14, 18],
    [0.28, 17, 45, 58],
    [0.56, 24, 112, 139],
    [0.78, 53, 184, 221],
    [1, 247, 192, 72],
  ];
  const upperIndex = stops.findIndex(([position]) => position >= value);
  if (upperIndex <= 0) return stops[0]!.slice(1) as [number, number, number];
  const lower = stops[upperIndex - 1]!;
  const upper = stops[upperIndex]!;
  const progress = (value - lower[0]) / (upper[0] - lower[0]);
  return [1, 2, 3].map((index) => Math.round(lower[index]! + (upper[index]! - lower[index]!) * progress)) as [number, number, number];
}

function stemLabel(stem: SpectralStemName): string {
  return stem.charAt(0).toUpperCase() + stem.slice(1);
}

function toPercent(seconds: number, duration: number): number {
  return duration > 0 ? (Math.min(duration, Math.max(0, seconds)) / duration) * 100 : 0;
}

function formatRulerTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatPreciseTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}
