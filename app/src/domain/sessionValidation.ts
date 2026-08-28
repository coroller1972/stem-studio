import { STEM_NAMES, type RestoredSession, type TranscriptionFiles } from "./types";

export function parseRestoredSession(value: unknown): RestoredSession {
  const session = object(value, "session");
  string(session.sessionPath, "sessionPath");
  string(session.manifestPath, "manifestPath");
  string(session.sourceName, "sourceName");
  if (session.qualityProfile !== "standard" && session.qualityProfile !== "high") invalid("qualityProfile");
  const stems = object(session.stems, "stems");
  STEM_NAMES.forEach((name) => string(stems[name], `stems.${name}`));
  validateState(session.state);
  const transcriptions = object(session.transcriptions, "transcriptions");
  validateTranscriptionFiles(transcriptions.bass, "bass");
  validateTranscriptionFiles(transcriptions.drums, "drums");
  return value as RestoredSession;
}

function validateState(value: unknown) {
  const state = object(value, "state");
  nonNegative(state.currentTimeSeconds, "state.currentTimeSeconds");
  nonNegative(state.startMarkerSeconds, "state.startMarkerSeconds");
  unit(state.masterVolume, "state.masterVolume");
  const tracks = object(state.tracks, "state.tracks");
  STEM_NAMES.forEach((name) => {
    const track = object(tracks[name], `state.tracks.${name}`);
    unit(track.volume, `state.tracks.${name}.volume`);
    if (typeof track.muted !== "boolean" || typeof track.solo !== "boolean") invalid(`state.tracks.${name}`);
  });
}

function validateTranscriptionFiles(value: unknown, expectedTrack: "bass" | "drums") {
  if (value === null) return;
  const files = object(value, `transcriptions.${expectedTrack}`) as unknown as TranscriptionFiles<any>;
  string(files.eventsFile, `${expectedTrack}.eventsFile`);
  string(files.midiFile, `${expectedTrack}.midiFile`);
  string(files.musicXmlFile, `${expectedTrack}.musicXmlFile`);
  const transcription = object(files.transcription, `${expectedTrack}.transcription`);
  if (transcription.track !== expectedTrack) invalid(`${expectedTrack}.track`);
  const versions = expectedTrack === "bass" ? [1, 2, 3] : [1, 2];
  if (!versions.includes(transcription.schemaVersion as number)) invalid(`${expectedTrack}.schemaVersion`);
  validateTempoMap(transcription.tempoMap, expectedTrack);
  if (!Array.isArray(transcription.events)) invalid(`${expectedTrack}.events`);
  transcription.events.forEach((event, index) => validateEvent(event, expectedTrack, index));
  if (expectedTrack === "bass") {
    if (!Array.isArray(transcription.tuning) || ![4, 5].includes(transcription.tuning.length)) invalid("bass.tuning");
    if (!Array.isArray(transcription.tab)) invalid("bass.tab");
  }
}

function validateTempoMap(value: unknown, track: string) {
  const tempo = object(value, `${track}.tempoMap`);
  range(tempo.bpm, 20, 400, `${track}.tempoMap.bpm`);
  if (!Array.isArray(tempo.beats)) invalid(`${track}.tempoMap.beats`);
  const signature = object(tempo.timeSignature, `${track}.tempoMap.timeSignature`);
  positive(signature.numerator, `${track}.tempoMap.timeSignature.numerator`);
  positive(signature.denominator, `${track}.tempoMap.timeSignature.denominator`);
}

function validateEvent(value: unknown, track: "bass" | "drums", index: number) {
  const event = object(value, `${track}.events[${index}]`);
  string(event.id, `${track}.events[${index}].id`);
  range(event.velocity, 1, 127, `${track}.events[${index}].velocity`);
  if (track === "bass") {
    nonNegative(event.detectedStartSeconds, `bass.events[${index}].detectedStartSeconds`);
    positive(event.detectedEndSeconds, `bass.events[${index}].detectedEndSeconds`);
    range(event.midiPitch, 0, 127, `bass.events[${index}].midiPitch`);
  } else {
    nonNegative(event.detectedTimeSeconds, `drums.events[${index}].detectedTimeSeconds`);
    string(event.instrument, `drums.events[${index}].instrument`);
  }
}

function object(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid(path);
  return value as Record<string, unknown>;
}
function string(value: unknown, path: string) { if (typeof value !== "string" || !value.trim()) invalid(path); }
function unit(value: unknown, path: string) { range(value, 0, 1, path); }
function positive(value: unknown, path: string) { if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) invalid(path); }
function nonNegative(value: unknown, path: string) { if (typeof value !== "number" || !Number.isFinite(value) || value < 0) invalid(path); }
function range(value: unknown, minimum: number, maximum: number, path: string) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) invalid(path);
}
function invalid(path: string): never { throw new Error(`The saved session contains an invalid ${path}.`); }
