"""Supported desktop dimensions shared by API, runtime and agent tooling."""

from typing import Literal

Resolution = Literal["1280x720", "1440x900", "1920x1080"]
DEFAULT_RESOLUTION = "1440x900"
RESOLUTIONS = ("1280x720", "1440x900", "1920x1080")


def dimensions(resolution: str) -> tuple[int, int]:
    if resolution not in RESOLUTIONS:
        raise ValueError("Unsupported desktop resolution")
    width, height = resolution.split("x")
    return int(width), int(height)
