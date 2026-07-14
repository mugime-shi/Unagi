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
from app.services.forecast_export_service import (
    EXPORT_AREAS,
    publish_forecast_exports,
    write_forecast_exports,
)

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
    parser.add_argument("--upload", action="store_true", help="Publish to R2 (needs R2_* env) instead of local files")
    args = parser.parse_args()

    areas = (args.area,) if args.area else EXPORT_AREAS

    db = SessionLocal()
    try:
        if args.upload:
            keys = publish_forecast_exports(db, areas=areas, archive=not args.no_archive)
            if not keys:
                log.error("R2 is not configured (R2_ENDPOINT / R2_BUCKET / R2_ACCESS_KEY_ID) — nothing uploaded")
                return
            for key in keys:
                log.info("uploaded %s", key)
            log.info("Published %d objects for %s", len(keys), ", ".join(areas))
        else:
            written = write_forecast_exports(db, args.out, areas=areas, archive=not args.no_archive)
            for path in written:
                log.info("wrote %s", path)
            log.info("Exported %d files for %s", len(written), ", ".join(areas))
    finally:
        db.close()


if __name__ == "__main__":
    main()
