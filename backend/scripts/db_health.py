"""Ad-hoc DB health check against Supabase: size, per-table size, freshness."""

import os
import re

from sqlalchemy import create_engine, text


def load_supabase_url() -> str:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path) as f:
        for line in f:
            m = re.match(r"\s*SUPABASE_DATABASE_URL\s*=\s*(.+)", line)
            if m:
                url = m.group(1).strip().strip('"').strip("'")
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    raise RuntimeError("SUPABASE_DATABASE_URL not found in .env")


# table -> timestamp-ish column to probe for freshness
FRESH = {
    "spot_prices": None,
    "generation_mix": None,
    "balancing_prices": None,
    "load_forecast": None,
    "de_spot_price": None,
    "weather_forecast": None,
    "forecast_accuracy": None,
}


def main() -> None:
    engine = create_engine(load_supabase_url(), pool_pre_ping=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        print("=== column discovery (ts/date columns) ===")
        for tbl in FRESH:
            cols = conn.execute(
                text(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=:t
                    ORDER BY ordinal_position
                    """
                ),
                {"t": tbl},
            ).all()
            ts_cols = [c.column_name for c in cols if c.data_type in (
                "timestamp with time zone", "timestamp without time zone", "date")]
            print(f"  {tbl:<22} ts/date cols: {ts_cols}")
            # pick the most likely 'latest' column
            for pref in ("start_time", "timestamp", "target_date", "ts", "delivery_start", "time", "date", "created_at"):
                if pref in ts_cols:
                    FRESH[tbl] = pref
                    break
            if FRESH[tbl] is None and ts_cols:
                FRESH[tbl] = ts_cols[-1]

        print("\n=== freshness (max ts) + rows in last 7 days ===")
        for tbl, col in FRESH.items():
            if not col:
                print(f"  {tbl:<22} (no ts column found)")
                continue
            try:
                mx = conn.execute(text(f"SELECT max({col}) FROM {tbl}")).scalar()
                recent = conn.execute(
                    text(f"SELECT count(*) FROM {tbl} WHERE {col} >= now() - interval '7 days'")
                ).scalar()
                print(f"  {tbl:<22} max({col})={mx}   rows_last_7d={recent}")
            except Exception as e:
                print(f"  {tbl:<22} ERROR on {col}: {str(e)[:80]}")


if __name__ == "__main__":
    main()
