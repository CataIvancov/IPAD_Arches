#!/usr/bin/env python
"""Populate Geography Island / Pulau on all IPAD Place / Site resources.

Uses the existing Island - Indonesia controlled list. Default is dry-run.
Pass --apply to write tiles and reindex.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ipad.settings")

import django

django.setup()

from django.db import connection, transaction

from arches.app.models.models import ResourceInstance, TileModel
from arches.app.models.tile import Tile

from ipad.island_assignment import (
    ISLAND_NODE_ID,
    classify_island,
    ensure_island_items,
    island_tile_value,
)

PLACE_GRAPHID = "de49aafc-dfa5-11ef-8d94-3565fe170f74"
GEO_NODEGROUP = "de49ab03-dfa5-11ef-8d94-3565fe170f74"
NAME_NODEGROUP = "de49ab01-dfa5-11ef-8d94-3565fe170f74"
NAME_NODE = "de49ab7d-dfa5-11ef-8d94-3565fe170f74"
ADDRESS_NODE = "de49ab10-dfa5-11ef-8d94-3565fe170f74"


def i18n_value(data) -> str:
    if not data:
        return ""
    if isinstance(data, dict):
        inner = data.get("en") or next(iter(data.values()), None)
        if isinstance(inner, dict):
            return str(inner.get("value") or "")
        if isinstance(inner, str):
            return inner
    return str(data)


def current_island_label(tiledata: dict) -> str:
    value = tiledata.get(ISLAND_NODE_ID)
    if not value:
        return ""
    if isinstance(value, list) and value:
        labels = value[0].get("labels") or []
        for label in labels:
            if label.get("language_id") == "en":
                return label.get("value") or ""
        if labels:
            return labels[0].get("value") or ""
    return ""


def load_sites() -> list[dict]:
    coords: dict[str, tuple[float | None, float | None]] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT g.resourceinstanceid::text,
                   ST_X(ST_Transform(ST_Centroid(g.geom), 4326)),
                   ST_Y(ST_Transform(ST_Centroid(g.geom), 4326))
            FROM geojson_geometries g
            JOIN resource_instances r ON r.resourceinstanceid = g.resourceinstanceid
            WHERE r.graphid = %s
            """,
            [PLACE_GRAPHID],
        )
        for rid, lon, lat in cursor.fetchall():
            coords[rid] = (lon, lat)

    names = {}
    for tile in TileModel.objects.filter(
        nodegroup_id=NAME_NODEGROUP,
        resourceinstance__graph_id=PLACE_GRAPHID,
    ).only("resourceinstance_id", "data"):
        names[str(tile.resourceinstance_id)] = i18n_value(tile.data.get(NAME_NODE))

    geo_tiles = {
        str(t.resourceinstance_id): t
        for t in TileModel.objects.filter(
            nodegroup_id=GEO_NODEGROUP,
            resourceinstance__graph_id=PLACE_GRAPHID,
        )
    }
    sites = []
    for resource in ResourceInstance.objects.filter(graph_id=PLACE_GRAPHID).only(
        "resourceinstanceid", "legacyid"
    ):
        rid = str(resource.pk)
        tile = geo_tiles.get(rid)
        lon, lat = coords.get(rid, (None, None))
        address = i18n_value(tile.data.get(ADDRESS_NODE)) if tile else ""
        sites.append(
            {
                "resource_id": rid,
                "legacyid": resource.legacyid or "",
                "name": names.get(rid, ""),
                "address": address,
                "lon": lon,
                "lat": lat,
                "tile": tile,
                "current": current_island_label(tile.data) if tile else "",
            }
        )
    return sites


def classify_sites(sites: list[dict]) -> list[dict]:
    for site in sites:
        label, method = classify_island(site["address"], site["lon"], site["lat"])
        site["island"] = label
        site["method"] = method
        site["changed"] = bool(label) and label != site["current"]
    return sites


def apply_updates(sites: list[dict]) -> tuple[int, int]:
    ensure_island_items()
    updated = created = 0
    for site in sites:
        if not site["island"] or not site["changed"]:
            continue
        value = island_tile_value(site["island"])
        tile = site["tile"]
        if tile is None:
            tile = Tile()
            tile.nodegroup_id = GEO_NODEGROUP
            tile.resourceinstance_id = site["resource_id"]
            tile.data = {ISLAND_NODE_ID: value}
            tile.save(index=False, user=None)
            created += 1
            continue
        wrapper = Tile.objects.get(pk=tile.pk)
        wrapper.data[ISLAND_NODE_ID] = value
        wrapper.save(index=False, user=None)
        updated += 1
    return updated, created


def reindex() -> None:
    from django.core import management

    print("indexing elasticsearch...")
    management.call_command(
        "es",
        "index_resources_by_type",
        resource_types=PLACE_GRAPHID,
        verbosity=1,
    )


def print_report(sites: list[dict]) -> None:
    counts = Counter(site["island"] or "(unmatched)" for site in sites)
    methods = Counter(site["method"] for site in sites)
    print(f"sites={len(sites)}")
    print("by island:")
    for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {count:4d}  {label}")
    print("by method:")
    for label, count in methods.most_common():
        print(f"  {count:4d}  {label}")
    unmatched = [site for site in sites if not site["island"]]
    if unmatched:
        print("UNMATCHED:")
        for site in unmatched:
            print(
                f"  {site['legacyid']}\t{site['name']}\t"
                f"{site['lon']}\t{site['lat']}\t{site['address']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write tiles and reindex")
    args = parser.parse_args()

    sites = classify_sites(load_sites())
    print_report(sites)
    unmatched = sum(1 for site in sites if not site["island"])
    to_write = sum(1 for site in sites if site["changed"])
    print(f"unmatched={unmatched} would_write={to_write}")
    if not args.apply:
        print("dry-run; pass --apply to write")
        return 1 if unmatched else 0

    if unmatched:
        print("refusing --apply while sites remain unmatched", file=sys.stderr)
        return 1

    with transaction.atomic():
        updated, created = apply_updates(sites)
    print(f"updated={updated} created={created}")
    reindex()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
