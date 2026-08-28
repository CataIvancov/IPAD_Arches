#!/usr/bin/env python
"""Move the 68 Africa-misplaced Sangiran Place points to Sangiran, Java.

Matches ArkeOpen: POINT(110.841 -7.443) for IPAD_058 and IPAD_677–IPAD_743.

Updates only Geometric Place Expression on existing geometry tiles.
Does not delete tiles, does not run import_ipad_sites_to_arches.py,
does not touch External Media, names, or other graphs.

Default is dry-run. Pass --apply to write.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ipad.settings")

import django

django.setup()

from django.db import connection, transaction

from arches.app.models.resource import Resource
from arches.app.models.tile import Tile

GEOM_NODEGROUP = uuid.UUID("de49aafd-dfa5-11ef-8d94-3565fe170f74")
NODE_GEOM = "de49ab1f-dfa5-11ef-8d94-3565fe170f74"
PLACE_GRAPH = uuid.UUID("de49aafc-dfa5-11ef-8d94-3565fe170f74")
MEDIA_NODEGROUP = uuid.UUID("7d09bbdb-46de-4ca0-aeae-8dd385c25c80")

# ArkeOpen public.site for the same 68 IPAD_* codes.
SANGIRAN_LON = 110.841
SANGIRAN_LAT = -7.443
OLD_LON = -7.08133
OLD_LAT = 1.0181453


def legacy_ids() -> list[str]:
    ids = ["IPAD_058"] + [f"IPAD_{n}" for n in range(677, 744)]
    if len(ids) != 68:
        raise SystemExit(f"expected 68 ids, got {len(ids)}")
    return ids


def current_coords(tile: Tile) -> tuple[float, float]:
    feat = tile.data[NODE_GEOM]["features"][0]
    lon, lat = feat["geometry"]["coordinates"][:2]
    return float(lon), float(lat)


def set_coords(tile: Tile, lon: float, lat: float) -> None:
    feat = tile.data[NODE_GEOM]["features"][0]
    feat["geometry"]["type"] = "Point"
    feat["geometry"]["coordinates"] = [lon, lat]


def load_tiles(ids: list[str]) -> list[Tile]:
    tiles = list(
        Tile.objects.filter(
            resourceinstance__graph_id=PLACE_GRAPH,
            resourceinstance__legacyid__in=ids,
            nodegroup_id=GEOM_NODEGROUP,
        ).select_related("resourceinstance")
    )
    return tiles


def media_count() -> int:
    from arches.app.models.models import TileModel

    return TileModel.objects.filter(nodegroup_id=MEDIA_NODEGROUP).count()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ids = legacy_ids()
    tiles = load_tiles(ids)
    by_legacy = {t.resourceinstance.legacyid: t for t in tiles}

    missing = [i for i in ids if i not in by_legacy]
    extra = [t for t in tiles if t.resourceinstance.legacyid not in ids]
    wrong = []
    already = []
    for lid in ids:
        tile = by_legacy.get(lid)
        if tile is None:
            continue
        lon, lat = current_coords(tile)
        if abs(lon - SANGIRAN_LON) < 1e-6 and abs(lat - SANGIRAN_LAT) < 1e-6:
            already.append(lid)
        elif abs(lon - OLD_LON) < 1e-4 and abs(lat - OLD_LAT) < 1e-4:
            continue
        else:
            wrong.append((lid, lon, lat))

    media_before = media_count()
    print(
        f"ids={len(ids)} geom_tiles={len(tiles)} missing={missing} "
        f"extra={len(extra)} already_java={len(already)} unexpected_coords={wrong} "
        f"media_tiles={media_before}"
    )
    to_fix = [by_legacy[i] for i in ids if i in by_legacy and i not in already]
    print(f"to_update={len(to_fix)} target=POINT({SANGIRAN_LON} {SANGIRAN_LAT})")
    if missing or extra or wrong:
        print("refusing: id/coord mismatch", file=sys.stderr)
        return 2
    if not args.apply:
        print("dry-run; pass --apply to write")
        return 0

    updated = 0
    for tile in to_fix:
        set_coords(tile, SANGIRAN_LON, SANGIRAN_LAT)
        with transaction.atomic():
            tile.save(index=True)
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT refresh_tile_geojson_geometries(%s);", [tile.pk]
                )
        updated += 1
        if updated % 20 == 0:
            print(f"... {updated}/{len(to_fix)}")

    media_after = media_count()
    print(f"updated={updated} media_tiles_after={media_after}")
    if media_after != media_before:
        print("WARNING: External Media tile count changed", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
