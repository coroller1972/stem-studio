"""Resolve product profiles to concrete separation backends."""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from audio_io import AudioIO
from bs_roformer_separator import BSRoFormerSeparator
from demucs_separator import DemucsSeparator
from domain import StemSeparator
from errors import SeparationError
from registry import SeparationProfile

SeparatorBuilder = Callable[[SeparationProfile, Optional[AudioIO]], StemSeparator]


class SeparatorFactory:
    def __init__(self, builders: Iterable[tuple[str, SeparatorBuilder]]) -> None:
        self._builders: dict[str, SeparatorBuilder] = {}
        for backend_id, builder in builders:
            if backend_id in self._builders:
                raise ValueError(f"Duplicate separation backend: {backend_id}")
            self._builders[backend_id] = builder

    def create(
        self,
        profile: SeparationProfile,
        *,
        audio_io: AudioIO | None = None,
    ) -> StemSeparator:
        try:
            builder = self._builders[profile.backend_id]
        except KeyError as error:
            raise SeparationError(
                "Separation backend is unavailable.",
                f"No backend is registered for '{profile.backend_id}'.",
            ) from error
        return builder(profile, audio_io)


def _build_demucs(profile: SeparationProfile, audio_io: AudioIO | None) -> StemSeparator:
    return DemucsSeparator(
        model_id=profile.model_id,
        profile_id=profile.id,
        audio_io=audio_io,
    )


def _build_bs_roformer(profile: SeparationProfile, audio_io: AudioIO | None) -> StemSeparator:
    return BSRoFormerSeparator(
        model_id=profile.model_id,
        profile_id=profile.id,
        audio_io=audio_io,
    )


SEPARATOR_FACTORY = SeparatorFactory(
    [
        ("demucs", _build_demucs),
        ("bs_roformer", _build_bs_roformer),
    ]
)


def create_separator(
    profile: SeparationProfile,
    *,
    audio_io: AudioIO | None = None,
) -> StemSeparator:
    return SEPARATOR_FACTORY.create(profile, audio_io=audio_io)
