"""Feature registry. To add a feature, create a module exposing `FEATURE` and list it here."""

from homegram.features import core, shopping, topics, tracker
from homegram.features.base import Feature

FEATURES: list[Feature] = [
    core.FEATURE,
    topics.FEATURE,
    shopping.FEATURE,
    tracker.FEATURE,
]


def enabled_features(homeassistant: bool) -> list[Feature]:
    """Features available with the current configuration."""
    return [f for f in FEATURES if homeassistant or not f.requires_homeassistant]


__all__ = ["FEATURES", "Feature", "enabled_features"]
