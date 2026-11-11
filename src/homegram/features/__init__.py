"""Feature registry. To add a feature, create a module exposing `FEATURE` and list it here."""

from homegram.config import Settings
from homegram.features import core, energia, pulizie, scene, shopping, spazzatura, topics, tracker
from homegram.features.base import Feature

FEATURES: list[Feature] = [
    core.FEATURE,
    topics.FEATURE,
    shopping.FEATURE,
    tracker.FEATURE,
    scene.FEATURE,
    energia.FEATURE,
    pulizie.FEATURE,
    spazzatura.FEATURE,
]


def enabled_features(settings: Settings) -> list[Feature]:
    """Features available with the current configuration."""
    return [
        f
        for f in FEATURES
        if (settings.homeassistant_enabled or not f.requires_homeassistant)
        and (f.available is None or f.available(settings))
    ]


__all__ = ["FEATURES", "Feature", "enabled_features"]
