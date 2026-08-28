#!/usr/bin/env python
"""Import regional ipad-sites CSVs into IPAD Place / Site (Archeology).

Maps SITE_NAME -> Resource Name (Toponym), lon/lat -> Geometric Place Expression.
Stores SITE_SOURCE_ID (and optional localisation/comments) on General Description.
Skips rows without coordinates. Dedupes by SITE_SOURCE_ID (last file wins).
"""

from __future__ import annotations

import csv
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ipad.settings")

import django

django.setup()

from django.contrib.auth.models import User
from django.db import transaction

from arches.app.datatypes.datatypes import DataTypeFactory
from arches.app.models.graph import Graph
from arches.app.models.models import GraphModel
from arches.app.models.resource import Resource
from arches.app.models.tile import Tile
from arches_controlled_lists.models import ListItem
from ipad.island_assignment import ISLAND_NODE_ID, classify_island, island_tile_value

CSV_DIR = Path("/opt/ipad/arkeopen-repo/arke-platform/data/ipad-sites")
SKIP = {"ipad-sites-combined.csv", "ipad-sites-organized.csv"}

GRAPH_SLUG = "ipad_place_site_archeology"
NAME_NODEGROUP = uuid.UUID("de49ab01-dfa5-11ef-8d94-3565fe170f74")
GEOM_NODEGROUP = uuid.UUID("de49aafd-dfa5-11ef-8d94-3565fe170f74")
GEO_NODEGROUP = uuid.UUID("de49ab03-dfa5-11ef-8d94-3565fe170f74")

NODE_RESOURCE_NAME = "de49ab7d-dfa5-11ef-8d94-3565fe170f74"
NODE_NAME_TYPE = "de49ab88-dfa5-11ef-8d94-3565fe170f74"
NODE_DESCRIPTION = "de49ab64-dfa5-11ef-8d94-3565fe170f74"
NODE_GEOM = "de49ab1f-dfa5-11ef-8d94-3565fe170f74"
NODE_CRS = "de49ab4f-dfa5-11ef-8d94-3565fe170f74"
NODE_ADDRESS = "de49ab10-dfa5-11ef-8d94-3565fe170f74"
NODE_ISLAND = ISLAND_NODE_ID

TOPONYM_ITEM_ID = uuid.UUID("8b7efbac-11a5-4063-8cb4-e1beeced3e9c")


def i18n(text: str, lang: str = "en") -> dict:
    return {lang: {"value": text, "direction": "ltr"}}


def load_rows() -> list[dict]:
    by_id: dict[str, dict] = {}
    files = sorted(p for p in CSV_DIR.glob("ipad-sites-*.csv") if p.name not in SKIP)
    if not files:
        raise SystemExit(f"No ipad-sites csv files in {CSV_DIR}")
    skipped_geo = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for raw in reader:
                row = {}
                for k, v in raw.items():
                    key = (k or "").strip()
                    if isinstance(v, list):
                        v = next((x for x in v if x), "")
                    row[key] = (v or "").strip()
                sid = row.get("SITE_SOURCE_ID") or ""
                name = row.get("SITE_NAME") or ""
                if not sid or not name:
                    continue
                try:
                    lon = float(row.get("LONGITUDE") or "")
                    lat = float(row.get("LATITUDE") or "")
                except ValueError:
                    skipped_geo += 1
                    continue
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    skipped_geo += 1
                    continue
                by_id[sid] = {
                    "id": sid,
                    "name": name,
                    "lon": lon,
                    "lat": lat,
                    "loc": row.get("LOCALISATION") or "",
                    "comments": row.get("COMMENTS") or "",
                    "proj": row.get("PROJECTION_SYSTEM") or "4326",
                    "source_file": path.name,
                }
    print(f"files={len(files)} unique_with_coords={len(by_id)} skipped_no_geo={skipped_geo}")
    return list(by_id.values())


def description_for(row: dict) -> str:
    parts = [row["id"]]
    if row["loc"]:
        parts.append(row["loc"])
    if row["comments"]:
        parts.append(row["comments"])
    parts.append(f"Imported from {row['source_file']}")
    return " | ".join(parts)


def import_row(row: dict, graph, toponym_value, geo_dt, user, existing: dict):
    legacy = row["id"]
    resource = existing.get(legacy)
    if resource is None:
        resource = Resource(graph_id=graph.graphid, legacyid=legacy)
        created = True
    else:
        resource = Resource.objects.get(pk=resource)
        created = False
        resource.tiles = []

    name_tile = Tile()
    name_tile.tileid = uuid.uuid4()
    name_tile.nodegroup_id = NAME_NODEGROUP
    name_tile.data = {
        NODE_RESOURCE_NAME: i18n(row["name"]),
        NODE_NAME_TYPE: [toponym_value],
        NODE_DESCRIPTION: i18n(description_for(row)),
    }
    geom_tile = Tile()
    geom_tile.tileid = uuid.uuid4()
    geom_tile.nodegroup_id = GEOM_NODEGROUP
    geom_tile.data = {
        NODE_GEOM: geo_dt.transform_value_for_tile(f"POINT({row['lon']} {row['lat']})"),
        NODE_CRS: i18n(f"EPSG:{row['proj']}" if row["proj"].isdigit() else row["proj"]),
    }
    resource.tiles = [name_tile, geom_tile]
    island_label, _method = classify_island(row["loc"], row["lon"], row["lat"])
    if row["loc"] or island_label:
        addr_tile = Tile()
        addr_tile.tileid = uuid.uuid4()
        addr_tile.nodegroup_id = GEO_NODEGROUP
        addr_tile.data = {}
        if row["loc"]:
            addr_tile.data[NODE_ADDRESS] = i18n(row["loc"])
        if island_label:
            addr_tile.data[NODE_ISLAND] = island_tile_value(island_label)
        resource.tiles.append(addr_tile)
    if not created:
        from arches.app.models.models import TileModel

        TileModel.objects.filter(resourceinstance=resource).delete()
    resource.save(index=False, user=user)
    return created


def main():
    rows = load_rows()
    graph = Graph.objects.get(slug=GRAPH_SLUG, source_identifier=None)
    if not graph.is_active:
        GraphModel.objects.filter(pk=graph.pk).update(is_active=True)
        print("activated graph", GRAPH_SLUG)

    toponym = ListItem.objects.get(pk=TOPONYM_ITEM_ID)
    toponym_value = toponym.build_tile_value()
    geo_dt = DataTypeFactory().get_instance("geojson-feature-collection")
    user = User.objects.get(pk=1)

    from arches.app.models.models import ResourceInstance

    existing = dict(
        ResourceInstance.objects.filter(
            graph_id=graph.graphid, legacyid__isnull=False
        ).values_list("legacyid", "resourceinstanceid")
    )

    created = updated = failed = 0
    failures = []
    for i, row in enumerate(rows, 1):
        try:
            with transaction.atomic():
                was_new = import_row(row, graph, toponym_value, geo_dt, user, existing)
            if was_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            failed += 1
            failures.append((row["id"], str(exc)))
            if failed <= 8:
                print(f"FAIL {row['id']}: {exc}", file=sys.stderr)
        if i % 100 == 0:
            print(f"... {i}/{len(rows)}")

    print(f"created={created} updated={updated} failed={failed}")
    if failures and failed > 8:
        print(f"{failed - 8} additional failures")

    print("indexing elasticsearch...")
    from django.core import management

    management.call_command(
        "es",
        "index_resources_by_type",
        resource_types=str(graph.graphid),
        verbosity=1,
    )


if __name__ == "__main__":
    main()
