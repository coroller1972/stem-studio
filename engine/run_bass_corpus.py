#!/usr/bin/env python3
"""Run reproducible bass-transcription QA cases and detect regressions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bass_reference_evaluation import evaluate_bass_reference
from basic_pitch_transcriber import BasicPitchBassTranscriber
from torchcrepe_transcriber import TorchCrepeBassTranscriber
from transcription_domain import TranscriptionProgressReporter
from transcription_pipeline import TranscriptionEngine

REGRESSION_RULES: dict[str, tuple[str, float]] = {
    "noteF1": ("higher", 0.02),
    "onsetF1": ("higher", 0.02),
    "pitchAccuracyOnMatchedOnsets": ("higher", 0.02),
    "shortNoteRecall": ("higher", 0.03),
    "repeatedNoteRecall": ("higher", 0.03),
    "lowBRecall": ("higher", 0.03),
    "octaveErrorRate": ("lower", 0.02),
    "medianOnsetErrorSeconds": ("lower", 0.01),
    "medianDurationErrorSeconds": ("lower", 0.03),
}


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    audio_path: Path
    reference_midi_path: Path
    reference_bpm: float
    onset_tolerance_seconds: float
    alignment_offset_seconds: float | None
    tuning: tuple[int, ...]
    beat_source_path: Path | None
    predictions: dict[str, Path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--engine",
        action="append",
        choices=("basic-pitch", "torchcrepe"),
        help="Run an engine before evaluation; repeat to compare both.",
    )
    parser.add_argument("--output", type=Path, default=Path("qa/results"))
    parser.add_argument("--models-dir", type=Path)
    parser.add_argument(
        "--prediction",
        action="append",
        metavar="CASE/ENGINE=PATH",
        help="Evaluate an existing bass.json without running inference.",
    )
    parser.add_argument("--baseline", type=Path, help="Fail when metrics regress beyond tolerances.")
    parser.add_argument("--write-baseline", type=Path, help="Write the current report as a baseline.")
    args = parser.parse_args(argv)

    cases = load_manifest(args.manifest)
    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    requested_engines = tuple(dict.fromkeys(args.engine or ()))
    prediction_overrides = _parse_prediction_overrides(args.prediction or ())
    reports: list[dict[str, object]] = []
    for case in cases:
        predictions = dict(case.predictions)
        predictions.update(
            {
                engine_id: path
                for (case_id, engine_id), path in prediction_overrides.items()
                if case_id == case.case_id
            }
        )
        for engine_id in requested_engines:
            predictions[engine_id] = transcribe_case(
                case,
                engine_id,
                output_root / case.case_id / engine_id,
                args.models_dir,
            )
        if not predictions:
            raise ValueError(
                f"Case {case.case_id!r} has no prediction; add --engine or a predictions entry."
            )
        for engine_id, prediction_path in predictions.items():
            report = evaluate_bass_reference(
                prediction_path,
                case.reference_midi_path,
                reference_bpm=case.reference_bpm,
                onset_tolerance_seconds=case.onset_tolerance_seconds,
                alignment_offset_seconds=case.alignment_offset_seconds,
            )
            reports.append(
                {
                    "caseId": case.case_id,
                    "engineId": engine_id,
                    **report.to_payload(),
                }
            )

    payload: dict[str, object] = {
        "schemaVersion": 1,
        "manifest": str(args.manifest.expanduser().resolve()),
        "regressionRules": {
            metric: {"direction": direction, "tolerance": tolerance}
            for metric, (direction, tolerance) in REGRESSION_RULES.items()
        },
        "results": reports,
    }
    report_path = output_root / "bass-corpus-report.json"
    _write_json(report_path, payload)
    if args.write_baseline:
        _write_json(args.write_baseline.expanduser().resolve(), _baseline_payload(payload))
    failures = compare_with_baseline(payload, args.baseline) if args.baseline else []
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failures:
        print("\nRegression(s):", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 2
    return 0


def load_manifest(path: Path) -> tuple[CorpusCase, ...]:
    manifest_path = path.expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError("Unsupported bass corpus manifest.")
    cases: list[CorpusCase] = []
    for value in payload["cases"]:
        case_id = str(value["id"])
        predictions = {
            str(engine): _resolve_path(str(prediction), manifest_path.parent)
            for engine, prediction in value.get("predictions", {}).items()
        }
        beat_source = value.get("beatSourcePath")
        cases.append(
            CorpusCase(
                case_id=case_id,
                audio_path=_resolve_path(str(value["audioPath"]), manifest_path.parent),
                reference_midi_path=_resolve_path(
                    str(value["referenceMidiPath"]), manifest_path.parent
                ),
                reference_bpm=float(value["referenceBpm"]),
                onset_tolerance_seconds=float(value.get("onsetToleranceSeconds", 0.08)),
                alignment_offset_seconds=(
                    float(value["alignmentOffsetSeconds"])
                    if value.get("alignmentOffsetSeconds") is not None
                    else None
                ),
                tuning=tuple(int(note) for note in value.get("tuning", (23, 28, 33, 38, 43))),
                beat_source_path=(
                    _resolve_path(str(beat_source), manifest_path.parent) if beat_source else None
                ),
                predictions=predictions,
            )
        )
    return tuple(cases)


def transcribe_case(
    case: CorpusCase,
    engine_id: str,
    output_dir: Path,
    models_dir: Path | None,
) -> Path:
    if not case.audio_path.is_file():
        raise FileNotFoundError(case.audio_path)
    if engine_id == "basic-pitch":
        transcriber = BasicPitchBassTranscriber(models_dir or _models_dir_from_environment())
    elif engine_id == "torchcrepe":
        transcriber = TorchCrepeBassTranscriber(models_dir or _models_dir_from_environment())
    else:
        raise ValueError(f"Unknown bass engine: {engine_id}")
    last_stage: str | None = None

    def progress(update: Any) -> None:
        nonlocal last_stage
        if update.stage != last_stage:
            last_stage = update.stage
            print(
                f"[{case.case_id}/{engine_id}] {update.stage}: {update.message}",
                file=sys.stderr,
                flush=True,
            )

    result = TranscriptionEngine(bass_transcriber=transcriber).transcribe_bass(
        case.audio_path,
        output_dir,
        TranscriptionProgressReporter(progress),
        beat_source=case.beat_source_path,
        tuning=case.tuning,
    )
    return result.events_file


def compare_with_baseline(payload: dict[str, object], baseline_path: Path) -> list[str]:
    baseline = json.loads(baseline_path.expanduser().read_text(encoding="utf-8"))
    current_by_key = {
        (item["caseId"], item["engineId"]): item
        for item in payload.get("results", [])
    }
    failures: list[str] = []
    for previous in baseline.get("results", []):
        key = (previous["caseId"], previous["engineId"])
        current = current_by_key.get(key)
        if current is None:
            failures.append(f"{key[0]}/{key[1]} is missing from the current report")
            continue
        previous_metrics = previous["metrics"]
        current_metrics = current["metrics"]
        for metric, (direction, tolerance) in REGRESSION_RULES.items():
            old = float(previous_metrics[metric])
            new = float(current_metrics[metric])
            regressed = new < old - tolerance if direction == "higher" else new > old + tolerance
            if regressed:
                failures.append(
                    f"{key[0]}/{key[1]} {metric}: {old:.4f} -> {new:.4f}"
                )
    return failures


def _resolve_path(value: str, base: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    return expanded.resolve() if expanded.is_absolute() else (base / expanded).resolve()


def _parse_prediction_overrides(values: tuple[str, ...] | list[str]) -> dict[tuple[str, str], Path]:
    result: dict[tuple[str, str], Path] = {}
    for value in values:
        target, separator, raw_path = value.partition("=")
        case_id, slash, engine_id = target.partition("/")
        if not separator or not slash or not case_id or not engine_id or not raw_path:
            raise ValueError("Prediction overrides must use CASE/ENGINE=PATH.")
        result[(case_id, engine_id)] = Path(os.path.expandvars(raw_path)).expanduser().resolve()
    return result


def _baseline_payload(payload: dict[str, object]) -> dict[str, object]:
    results = []
    for item in payload.get("results", []):
        results.append(
            {
                key: value
                for key, value in item.items()
                if key not in ("predictionPath", "referencePath")
            }
        )
    return {
        "schemaVersion": 1,
        "regressionRules": payload.get("regressionRules", {}),
        "results": results,
    }


def _models_dir_from_environment() -> Path | None:
    value = os.environ.get("STEM_STUDIO_MODELS_DIR")
    return Path(value) if value else None


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
