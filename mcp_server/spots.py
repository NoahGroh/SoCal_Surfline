"""Spot database loader."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import yaml

SPOTS_FILE = Path(__file__).parent / "spots.yaml"


@lru_cache(maxsize=1)
def _load() -> dict:
    with SPOTS_FILE.open() as f:
        return yaml.safe_load(f)


def all_regions() -> dict[str, str]:
    return _load()["regions"]


def all_spots() -> list[dict]:
    return _load()["spots"]


def get_spot(spot_id: str) -> dict | None:
    for s in all_spots():
        if s["id"] == spot_id:
            return s
    return None


def spots_in_region(region_id: str) -> list[dict]:
    return [s for s in all_spots() if s["region"] == region_id]
