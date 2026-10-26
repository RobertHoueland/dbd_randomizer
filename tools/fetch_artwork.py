"""Optional cache warmer; downloads to the device cache, never the project."""

from urllib.request import Request, urlopen

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QImage

from dbd_randomizer.artwork import artwork_index, artwork_url, cache_path, save_artwork


def main():
    app = QCoreApplication.instance() or QCoreApplication([])
    app.setApplicationName("DBD Randomizer")
    app.setOrganizationName("DBDRandomizer")
    manifest = artwork_index()
    for kind in ("characters", "perks", "items", "addons"):
        for entry_id in manifest.get(kind, {}):
            target = cache_path(kind, entry_id)
            if target.exists() and not QImage(str(target)).isNull():
                continue
            request = Request(
                artwork_url(kind, entry_id), headers={"User-Agent": "DBD-Randomizer/1.0"}
            )
            with urlopen(request, timeout=15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024 or not save_artwork(target, data, kind):
                raise ValueError(f"Could not cache artwork for {kind}/{entry_id}")
    print("Device artwork cache ready.")


if __name__ == "__main__":
    main()
