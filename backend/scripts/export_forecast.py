"""
Export the public v1 forecast feed as static JSON files.

Usage:
    python -m scripts.export_forecast                     # all areas → ./export_out
    python -m scripts.export_forecast --out /tmp/feed
    python -m scripts.export_forecast --area SE3          # single area
    python -m scripts.export_forecast --no-archive        # skip daily snapshot

Reads the freshest d+1..d+7 predictions from forecast_accuracy and writes
CDN-ready files (see forecast_export_service for layout and schema contract).
"""

import argparse
import logging

from app.db.database import SessionLocal
from app.services.forecast_export_service import EXPORT_AREAS, write_forecast_exports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export public forecast JSON files")
    parser.add_argument("--out", default="./export_out", help="Output directory (default: ./export_out)")
    parser.add_argument("--area", default=None, help="Single area SE1-SE4 (default: all)")
    parser.add_argument("--no-archive", action="store_true", help="Skip the frozen daily snapshot")
    args = parser.parse_args()

    areas = (args.area,) if args.area else EXPORT_AREAS

    db = SessionLocal()
    try:
        written = write_forecast_exports(db, args.out, areas=areas, archive=not args.no_archive)
    finally:
        db.close()

    for path in written:
        log.info("wrote %s", path)
    log.info("Exported %d files for %s", len(written), ", ".join(areas))


if __name__ == "__main__":
    main()
