"""Validated snapshots, bounded network requests, and atomic cache replacement."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from urllib.request import Request, urlopen

from .core import Catalog

API_URL = "https://dbd.tricky.lol/api/"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DOWNLOAD_BUDGET_SECONDS = 30


class RefreshCancelled(Exception):
    """The caller requested cooperative cancellation."""


@dataclass(frozen=True)
class Snapshot:
    catalog: Catalog
    fetched_at: str
    source: str
    warning: str = ""


def decode(payload: dict, source: str) -> Snapshot:
    if not isinstance(payload, dict):
        raise ValueError("Invalid catalog document.")
    timestamp = payload.get("fetched_at")
    if not isinstance(timestamp, str):
        raise ValueError("Missing catalog timestamp.")
    datetime.fromisoformat(timestamp)
    if not all(isinstance(payload.get(kind), dict) for kind in ("items", "addons")):
        raise ValueError("The saved roster predates equipment support. Refresh the roster.")
    catalog = Catalog.from_payload(payload)
    if not catalog.items or any(
        not catalog.pool("addons", role) for role in ("survivor", "killer")
    ):
        raise ValueError("The equipment catalog is incomplete.")
    # Powers are filtered out of the rollable item pool, but their raw records are
    # still needed to verify that killer add-ons can be matched to a real power.
    for character in catalog.pool("characters", "killer"):
        power = payload["items"].get(character.power, {})
        if power.get("type") != "power" or power.get("role") != "killer":
            raise ValueError("Missing killer power compatibility data.")
    return Snapshot(catalog, timestamp, source)


class DataService:
    def __init__(self, cache_dir: Path):
        self.cache_path = cache_dir / "catalog.json"

    def load(self) -> Snapshot:
        warning = ""
        if self.cache_path.exists():
            try:
                return decode(
                    json.loads(self.cache_path.read_text(encoding="utf-8")), "Cached roster"
                )
            except (OSError, ValueError, TypeError):
                warning = "The saved roster is outdated or unreadable. Using the bundled roster."
        # Startup never needs a network request, even when the user's cache is corrupt.
        # Package resources also work when installed outside the source checkout.
        payload = json.loads(
            files("dbd_randomizer").joinpath("data/catalog.json").read_text("utf-8")
        )
        bundled = decode(payload, "Bundled roster")
        return Snapshot(bundled.catalog, bundled.fetched_at, bundled.source, warning)

    def refresh(self, cancelled: Callable[[], bool] = lambda: False) -> Snapshot:
        # Share one budget across all endpoints; wall-clock adjustments must not extend it.
        deadline = time.monotonic() + DOWNLOAD_BUDGET_SECONDS

        def checkpoint():
            if cancelled():
                raise RefreshCancelled("Roster refresh cancelled.")
            if time.monotonic() >= deadline:
                raise TimeoutError("Roster download exceeded its time budget.")

        payload = {"fetched_at": datetime.now(timezone.utc).isoformat()}
        for endpoint in ("characters", "perks", "items", "addons"):
            checkpoint()
            request = Request(API_URL + endpoint, headers={"User-Agent": "DBDRandomizer/1.0"})
            with urlopen(request, timeout=12) as response:
                body = bytearray()
                while True:
                    checkpoint()
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("The roster response was unexpectedly large.")
            checkpoint()
            payload[endpoint] = json.loads(body)
        # Validate the combined roster before touching the cache: individually valid
        # responses can still be missing the cross-references needed for equipment.
        snapshot = decode(payload, "Live roster")
        checkpoint()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Write in the same directory so replacement is atomic, even across filesystems.
        fd, name = tempfile.mkstemp(dir=self.cache_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
            # Cancellation during serialization should leave the last good cache intact.
            checkpoint()
            os.replace(name, self.cache_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return snapshot
