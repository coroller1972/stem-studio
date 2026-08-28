"""Stable product-quality profiles mapped to internal separation models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class UnknownProfileError(ValueError):
    pass


@dataclass(frozen=True)
class SeparationProfile:
    id: str
    label: str
    description: str
    backend_id: str
    model_id: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.id, self.label, self.description, self.backend_id, self.model_id)
        ):
            raise ValueError("A separation profile cannot contain empty fields.")


class ProfileRegistry:
    def __init__(self, profiles: Iterable[SeparationProfile]) -> None:
        self._profiles: dict[str, SeparationProfile] = {}
        for profile in profiles:
            if profile.id in self._profiles:
                raise ValueError(f"Duplicate separation profile: {profile.id}")
            self._profiles[profile.id] = profile

    def get(self, profile_id: str) -> SeparationProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as error:
            available = ", ".join(self.ids())
            raise UnknownProfileError(
                f"Unknown separation profile '{profile_id}'. Available: {available}"
            ) from error

    def ids(self) -> tuple[str, ...]:
        return tuple(self._profiles)

    def profiles(self) -> tuple[SeparationProfile, ...]:
        return tuple(self._profiles.values())


STANDARD_PROFILE = SeparationProfile(
    id="standard",
    label="Standard",
    description="Balanced four-stem separation for local use.",
    backend_id="demucs",
    model_id="htdemucs",
)

HIGH_PROFILE = SeparationProfile(
    id="high",
    label="High",
    description="Slower four-stem separation optimized for output quality.",
    backend_id="bs_roformer",
    model_id="roformer-model-bs-roformer-musdb18hq-by-zfturbo",
)

PROFILE_REGISTRY = ProfileRegistry([STANDARD_PROFILE, HIGH_PROFILE])
DEFAULT_PROFILE_ID = STANDARD_PROFILE.id


def get_profile(profile_id: str) -> SeparationProfile:
    return PROFILE_REGISTRY.get(profile_id)
