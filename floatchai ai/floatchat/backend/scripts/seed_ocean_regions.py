#!/usr/bin/env python3
"""
Seed ocean region polygons into the ocean_regions table.

Usage:
    python scripts/seed_ocean_regions.py

Reads ocean region polygon data from scripts/data/ocean_regions.geojson and
upserts each feature into the ocean_regions table.

The script is fully idempotent — running it multiple times produces the same
database state.  Uses INSERT ... ON CONFLICT (region_name) DO UPDATE to
overwrite the geometry and metadata on re-runs.

Requires:
    - DATABASE_URL environment variable (or defaults to PgBouncer on 5433)
    - The ocean_regions table must already exist (migration 002)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

logger = structlog.get_logger("seed_ocean_regions")

# Locate the GeoJSON file relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
GEOJSON_PATH = SCRIPT_DIR / "data" / "ocean_regions.geojson"


def load_geojson(path: Path) -> list[dict]:
    """Load and return the features list from a GeoJSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    features = data.get("features", [])
    if not features:
        raise ValueError(f"No features found in {path}")
    return features


def _build_parent_map(features: list[dict]) -> dict[str, int | None]:
    """
    First pass: insert all regions without parent_region_id so we can collect
    their IDs, then return a mapping of region_name → region_id.
    """
    return {}  # Handled inside seed()


def seed(db_url: str) -> None:
    """Connect to the database and upsert all ocean regions."""
    engine = create_engine(db_url)
    make_session = sessionmaker(bind=engine)

    features = load_geojson(GEOJSON_PATH)
    logger.info("loaded_geojson", path=str(GEOJSON_PATH), regions=len(features))

    with make_session() as session:
        # ── Pass 1: upsert every region without parent_region_id ──────────
        for feat in features:
            props = feat["properties"]
            geom_json = json.dumps(feat["geometry"])
            region_name = props["region_name"]
            region_type = props.get("region_type")
            description = props.get("description")

            session.execute(
                text("""
                    INSERT INTO ocean_regions (region_name, region_type, description, geom)
                    VALUES (
                        :region_name,
                        :region_type,
                        :description,
                        ST_GeogFromGeoJSON(:geom_json)
                    )
                    ON CONFLICT (region_name) DO UPDATE SET
                        region_type  = EXCLUDED.region_type,
                        description  = EXCLUDED.description,
                        geom         = EXCLUDED.geom
                """),
                {
                    "region_name": region_name,
                    "region_type": region_type,
                    "description": description,
                    "geom_json": geom_json,
                },
            )
            logger.info("upserted_region", region_name=region_name)

        session.commit()

        # ── Pass 2: set parent_region_id where applicable ─────────────────
        # Build a name → id map
        rows = session.execute(
            text("SELECT region_id, region_name FROM ocean_regions")
        ).fetchall()
        name_to_id: dict[str, int] = {r.region_name: r.region_id for r in rows}

        for feat in features:
            props = feat["properties"]
            parent_name = props.get("parent_region_name")
            if parent_name and parent_name in name_to_id:
                session.execute(
                    text("""
                        UPDATE ocean_regions
                        SET parent_region_id = :parent_id
                        WHERE region_name = :region_name
                    """),
                    {
                        "parent_id": name_to_id[parent_name],
                        "region_name": props["region_name"],
                    },
                )
                logger.info(
                    "set_parent",
                    region=props["region_name"],
                    parent=parent_name,
                )

        session.commit()
        logger.info("seed_complete", total_regions=len(features))


def main() -> None:
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://floatchat:floatchat@localhost:5433/floatchat",
    )
    logger.info("starting_seed", db_url=db_url.split("@")[-1])  # log host only
    seed(db_url)


if __name__ == "__main__":
    main()
