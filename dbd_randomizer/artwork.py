"""On-demand artwork downloads into the device cache, never the source tree."""

import hashlib
import json
from collections import deque
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import QIODevice, QObject, QSaveFile, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MAX_BYTES = 8 * 1024 * 1024


@lru_cache(maxsize=1)
def artwork_index() -> dict:
    return json.loads(files("dbd_randomizer").joinpath("data/artwork.json").read_text("utf-8"))


def artwork_url(kind, entry_id):
    manifest = artwork_index()
    asset = manifest.get(kind, {}).get(entry_id)
    if not asset:
        return None
    source = asset.get("source", manifest["source"])
    revision = asset.get("revision", manifest["revision"])
    return (
        source.replace("github.com", "raw.githubusercontent.com")
        + "/"
        + revision
        + "/"
        + quote(asset["source_path"])
    )


def cache_path(kind, entry_id):
    url = artwork_url(kind, entry_id)
    if url is None:
        return None
    root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
    # Source changes invalidate the cache; no manifest-provided filesystem paths are used.
    return root / "artwork" / (hashlib.sha256(url.encode()).hexdigest() + ".png")


class ArtworkDownloads(QObject):
    ready = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.enabled = False
        self.network = QNetworkAccessManager(self)
        self.pending = deque()
        self.attempted = set()
        self.active = 0

    def request(self, kind, entry_id):
        key = (kind, entry_id)
        if not self.enabled or key in self.attempted or artwork_url(*key) is None:
            return
        # Failed requests are retried on the next launch, not on every paint/roll.
        self.attempted.add(key)
        self.pending.append(key)
        self._pump()

    def _pump(self):
        while self.pending and self.active < 4:
            key = self.pending.popleft()
            request = QNetworkRequest(QUrl(artwork_url(*key)))
            request.setTransferTimeout(15000)
            request.setRawHeader(b"User-Agent", b"DBD-Randomizer/1.0")
            reply = self.network.get(request)
            self.active += 1
            data = bytearray()

            def receive(reply=reply, data=data):
                data.extend(bytes(reply.readAll()))
                if len(data) > MAX_BYTES:
                    reply.abort()

            def finish(reply=reply, data=data, key=key, receive=receive):
                receive()
                try:
                    if (
                        reply.error() == QNetworkReply.NetworkError.NoError
                        and len(data) <= MAX_BYTES
                    ):
                        if save_artwork(cache_path(*key), bytes(data), key[0]):
                            self.ready.emit(*key)
                finally:
                    reply.deleteLater()
                    self.active -= 1
                    self._pump()

            reply.readyRead.connect(receive)
            reply.finished.connect(finish)


@lru_cache(maxsize=1)
def downloads():
    """Created on the GUI thread, after QApplication exists."""
    return ArtworkDownloads()


def save_artwork(path, data, kind):
    image = QImage.fromData(data)
    if image.isNull():
        return False
    bound = 320 if kind == "characters" else 160
    image = image.scaled(
        bound, bound, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        target = QSaveFile(str(path))
        if not target.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        if not image.save(target, "PNG"):
            target.cancelWriting()
            return False
        return target.commit()
    except OSError:
        return False


def entry_pixmap(kind: str, entry_id: str) -> QPixmap:
    """Return cached art immediately; queue missing/corrupt art without blocking."""
    path = cache_path(kind, entry_id)
    pixmap = QPixmap()
    if path is not None:
        if path.is_file():
            pixmap.load(str(path))
        if pixmap.isNull():
            downloads().request(kind, entry_id)
    return pixmap
