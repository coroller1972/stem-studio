"""Beat tracking adapters normalized to Stem Studio's TempoMap."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from errors import TranscriptionError
from transcription_domain import TempoBeat, TempoMap


class LibrosaBeatTracker:
    def track(self, audio_path: Path) -> TempoMap:
        try:
            import librosa
            import numpy as np
        except ImportError as error:
            raise TranscriptionError(
                "Unable to detect tempo reliably.",
                "Install the transcription dependencies from engine/requirements.txt.",
            ) from error

        try:
            audio, sample_rate = librosa.load(str(audio_path), sr=22_050, mono=True)
            onset_envelope = librosa.onset.onset_strength(y=audio, sr=sample_rate)
            tempo, beat_frames = librosa.beat.beat_track(
                onset_envelope=onset_envelope,
                sr=sample_rate,
                units="frames",
            )
            bpm = float(np.asarray(tempo).reshape(-1)[0])
            times = librosa.frames_to_time(beat_frames, sr=sample_rate)
            strengths = onset_envelope[np.clip(beat_frames, 0, max(0, len(onset_envelope) - 1))]
            downbeat_offset = infer_downbeat_offset(strengths, 4)
        except Exception as error:
            raise TranscriptionError("Unable to detect tempo reliably.", str(error)) from error

        if not 20 <= bpm <= 400 or len(times) < 2:
            raise TranscriptionError(
                "Unable to detect tempo reliably.",
                f"Beat tracker returned bpm={bpm!r} and {len(times)} beat positions.",
            )
        return TempoMap(
            bpm=bpm,
            beats=tuple(
                TempoBeat(index - downbeat_offset, float(time))
                for index, time in enumerate(times)
            ),
            tempo_candidates=metric_tempo_candidates(bpm),
        )


def metric_tempo_candidates(
    bpm: float,
    minimum_display_bpm: float = 55.0,
    maximum_display_bpm: float = 220.0,
) -> tuple[float, ...]:
    """Return plausible half/current/double-time interpretations."""

    candidates = {
        round(candidate, 6)
        for candidate in (bpm / 2, bpm, bpm * 2)
        if minimum_display_bpm <= candidate <= maximum_display_bpm
    }
    return tuple(sorted(candidates))


def infer_downbeat_offset(beat_strengths: Sequence[float], beats_per_measure: int) -> int:
    """Choose the metrically strongest phase, keeping phase zero if evidence is weak."""
    if beats_per_measure <= 0 or len(beat_strengths) < beats_per_measure * 2:
        return 0
    scores = []
    for phase in range(beats_per_measure):
        values = [float(value) for value in beat_strengths[phase::beats_per_measure]]
        scores.append(sum(values) / len(values))
    strongest = max(range(beats_per_measure), key=scores.__getitem__)
    mean_score = sum(scores) / len(scores)
    if scores[strongest] <= 0 or scores[strongest] < mean_score * 1.1:
        return 0
    return strongest


@contextmanager
def stable_beat_source(
    audio_path: Path,
    requested_source: Path | None,
    work_dir: Path,
) -> Iterator[Path]:
    """Yield a separator-independent mix when all four sibling stems exist."""

    stems = tuple(audio_path.parent / f"{name}.wav" for name in ("vocals", "drums", "bass", "other"))
    if not all(path.is_file() for path in stems):
        yield requested_source or audio_path
        return

    temporary_mix = work_dir / ".beat-mix.wav"
    try:
        _write_reconstructed_mix(stems, temporary_mix)
        yield temporary_mix
    finally:
        temporary_mix.unlink(missing_ok=True)


def _write_reconstructed_mix(stems: tuple[Path, ...], destination: Path) -> None:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as error:
        raise TranscriptionError(
            "Unable to reconstruct the mix for beat tracking.",
            "Install soundfile and NumPy from engine/requirements.txt.",
        ) from error

    try:
        with ExitStack() as stack:
            readers = [stack.enter_context(sf.SoundFile(path)) for path in stems]
            sample_rate = readers[0].samplerate
            channels = readers[0].channels
            if any(reader.samplerate != sample_rate or reader.channels != channels for reader in readers[1:]):
                raise ValueError("Separated stems do not share the same audio format")
            writer = stack.enter_context(
                sf.SoundFile(
                    destination,
                    mode="w",
                    samplerate=sample_rate,
                    channels=channels,
                    format="WAV",
                    subtype="FLOAT",
                )
            )
            while True:
                blocks = [reader.read(262_144, dtype="float32", always_2d=True) for reader in readers]
                frames = min(len(block) for block in blocks)
                if frames == 0:
                    break
                writer.write(np.sum([block[:frames] for block in blocks], axis=0))
    except Exception as error:
        raise TranscriptionError("Unable to reconstruct the mix for beat tracking.", str(error)) from error
