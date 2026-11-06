"""Feature registry. To add a feature, create a module exposing `FEATURE` and list it here."""

from homegram.features import core, shopping, topics
from homegram.features.base import Feature

FEATURES: list[Feature] = [
    core.FEATURE,
    topics.FEATURE,
    shopping.FEATURE,
]

__all__ = ["FEATURES", "Feature"]
