#!/usr/bin/env python
"""Phase 1: import Drive bibliography PDFs as external-media Information Resources.

Creates E73 Information Resource instances (legacyid gdrive:{file_id}) with one
E84 External Information Carrier tile each, then P129i Place → IR tiles.

Does not modify:
- import_ipad_sites_to_arches.py
- assessment P16 / information_resource on Place
- information_carrier (file-list), publication, external_xref
- existing Place metadata, geometry, or assessment tiles

Default is dry-run. Pass --apply to write.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ipad.settings")

import django

django.setup()

from django.contrib.auth.models import User
from django.db import transaction
from arches.app.models.graph import Graph
from arches.app.models.models import GraphModel, Node, ResourceInstance, TileModel
from arches.app.models.resource import Resource
from arches.app.models.tile import Tile
from arches_controlled_lists.models import ListItem

CSV_DIR = Path("/opt/ipad/arkeopen-repo/arke-platform/data/ipad-sites")
MATCHES_PATH = Path(
    "/opt/ipad/arkeopen-repo/arke-platform/data/bibliography-drive-matches.csv"
)
SKIP_FILES = {"ipad-sites-combined.csv", "ipad-sites-organized.csv"}

PLACE_SLUG = "ipad_place_site_archeology"
IR_SLUG = "information_resource_model"
EXPECTED_IR_GRAPHID = uuid.UUID("3caf329f-b8f7-11e6-84a5-026d961c88e6")
EXPECTED_PDFS = 9
EXPECTED_LINKS = 129

DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([^/\s?]+)")
ALLOWED_CONFIDENCE = {"exact", "high"}
SKIP_CONFIDENCE = {"review", "none"}
LEGACY_PREFIX = "gdrive:"
P129I = "http://www.cidoc-crm.org/cidoc-crm/P129i_is_subject_of"
P129 = "http://www.cidoc-crm.org/cidoc-crm/P129_is_about"
STORAGE_LIST_NAME = "IPAD storage backend"
STORAGE_ITEM_LABEL = "google_drive"
MIME_PDF = "application/pdf"

# Nodes this importer is forbidden to write.
FORBIDDEN_ALIASES = {
    "information_resource",  # Place assessment P16
    "information_carrier",
    "publication",
    "external_xref",
}


def i18n(text: str, lang: str = "en") -> dict:
    return {lang: {"value": text, "direction": "ltr"}}


def i18n_plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("en",):
            inner = value.get(key)
            if isinstance(inner, dict) and inner.get("value"):
                return str(inner["value"])
            if isinstance(inner, str) and inner:
                return inner
        for inner in value.values():
            if isinstance(inner, dict) and inner.get("value"):
                return str(inner["value"])
            if isinstance(inner, str) and inner:
                return inner
    return str(value)


def source_graph(slug: str) -> Graph:
    graph = Graph.objects.filter(slug=slug, source_identifier__isnull=True).first()
    if graph is None:
        raise SystemExit(f"ERROR: graph slug={slug} not found")
    return graph


def require_node(graph: Graph, alias: str, datatype: str | None = None) -> Node:
    nodes = list(Node.objects.filter(graph=graph, alias=alias))
    if len(nodes) != 1:
        raise SystemExit(
            f"ERROR: expected exactly one node alias={alias} on {graph.slug}, "
            f"found {len(nodes)}"
        )
    node = nodes[0]
    if datatype and node.datatype != datatype:
        raise SystemExit(
            f"ERROR: node {alias} datatype is {node.datatype}, expected {datatype}"
        )
    return node


def load_matches() -> tuple[dict[str, dict], set[str], int]:
    if not MATCHES_PATH.exists():
        raise SystemExit(f"ERROR: matches file missing: {MATCHES_PATH}")
    allowed: dict[str, dict] = {}
    skipped_ids: set[str] = set()
    skipped_rows = 0
    with MATCHES_PATH.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            confidence = (row.get("confidence") or "").strip().lower()
            drive_id = (row.get("drive_id") or "").strip()
            if confidence in SKIP_CONFIDENCE:
                skipped_rows += 1
                if drive_id:
                    skipped_ids.add(drive_id)
                continue
            if confidence not in ALLOWED_CONFIDENCE:
                continue
            if not drive_id:
                continue
            name = (row.get("drive_name") or "").strip()
            prev = allowed.get(drive_id)
            if prev is None:
                allowed[drive_id] = {
                    "confidence": confidence,
                    "filename": name,
                }
            elif name and not prev["filename"]:
                prev["filename"] = name
    return allowed, skipped_ids, skipped_rows


def load_bibliography_links(
    allowed: dict[str, dict], skipped_ids: set[str]
) -> tuple[dict[str, dict], list[tuple[str, str]], dict]:
    files = sorted(p for p in CSV_DIR.glob("ipad-sites-*.csv") if p.name not in SKIP_FILES)
    if not files:
        raise SystemExit(f"ERROR: no regional ipad-sites csv files in {CSV_DIR}")

    files_by_id: dict[str, dict] = {}
    links: set[tuple[str, str]] = set()
    skipped_review_bib = 0
    unmatched_ids: set[str] = set()
    empty_site = 0

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
                bib = row.get("BIBLIOGRAPHY") or ""
                ids = DRIVE_FILE_RE.findall(bib)
                if not ids:
                    continue
                site_id = row.get("SITE_SOURCE_ID") or ""
                for drive_id in ids:
                    if drive_id in skipped_ids or drive_id not in allowed:
                        if drive_id in skipped_ids:
                            skipped_review_bib += 1
                        else:
                            unmatched_ids.add(drive_id)
                        continue
                    if not site_id:
                        empty_site += 1
                        continue
                    meta = files_by_id.setdefault(
                        drive_id,
                        {
                            "file_id": drive_id,
                            "filename": allowed[drive_id]["filename"],
                            "confidence": allowed[drive_id]["confidence"],
                            "legacyid": f"{LEGACY_PREFIX}{drive_id}",
                            "sites": set(),
                        },
                    )
                    meta["sites"].add(site_id)
                    links.add((site_id, drive_id))

    extras = {
        "skipped_review_bibliography": skipped_review_bib,
        "unmatched_drive_ids": sorted(unmatched_ids),
        "empty_site_id": empty_site,
        "csv_files": len(files),
    }
    return files_by_id, sorted(links), extras


class GraphMap:
    def __init__(self):
        self.place = source_graph(PLACE_SLUG)
        self.ir = source_graph(IR_SLUG)
        self.errors: list[str] = []

        if self.ir.graphid != EXPECTED_IR_GRAPHID:
            self.errors.append(
                f"IR graphid {self.ir.graphid} != expected {EXPECTED_IR_GRAPHID}"
            )

        self.title = require_node(self.ir, "title", "string")
        self.carrier = require_node(self.ir, "external_information_carrier", "semantic")
        self.file_id = require_node(self.ir, "external_carrier_file_id", "string")
        self.storage = require_node(self.ir, "storage_backend", "reference")
        self.mime = require_node(self.ir, "mime_type", "string")
        self.caption = require_node(self.ir, "caption", "string")
        self.external_media = require_node(self.place, "external_media", "resource-instance")
        self.assessment_ir = require_node(self.place, "information_resource", "resource-instance")

        if self.file_id.nodegroup_id != self.carrier.nodeid:
            self.errors.append("external_carrier_file_id is not in the E84 carrier nodegroup")
        if self.storage.nodegroup_id != self.carrier.nodeid:
            self.errors.append("storage_backend is not in the E84 carrier nodegroup")
        if self.mime.nodegroup_id != self.carrier.nodeid:
            self.errors.append("mime_type is not in the E84 carrier nodegroup")
        if self.external_media.nodegroup_id != self.external_media.nodeid:
            self.errors.append("external_media is not its own nodegroup")

        graphs_cfg = (self.external_media.config or {}).get("graphs") or []
        ir_ok = any(
            str(g.get("graphid")) == str(EXPECTED_IR_GRAPHID) for g in graphs_cfg
        )
        if not ir_ok:
            self.errors.append(
                "external_media node is not configured for Information Resource Model "
                f"{EXPECTED_IR_GRAPHID}"
            )

        for alias in FORBIDDEN_ALIASES:
            if alias == "information_resource":
                continue
            try:
                node = require_node(self.ir, alias)
            except SystemExit as exc:
                self.errors.append(str(exc))
                continue
            # Presence is expected; we only refuse to write these nodegroups.
            setattr(self, f"forbidden_{alias}", node)

        try:
            item = ListItem.objects.get(
                list__name=STORAGE_LIST_NAME,
                list_item_values__value=STORAGE_ITEM_LABEL,
                list_item_values__valuetype_id="prefLabel",
            )
        except ListItem.DoesNotExist:
            self.errors.append(
                f"controlled list item {STORAGE_ITEM_LABEL!r} not found on {STORAGE_LIST_NAME!r}"
            )
            item = None
        except ListItem.MultipleObjectsReturned:
            self.errors.append(f"multiple {STORAGE_ITEM_LABEL!r} list items")
            item = None
        self.storage_item = item
        self.storage_value = item.build_tile_value() if item is not None else None

        self.user = User.objects.get(pk=1)

    @property
    def allowed_nodegroups(self) -> set[uuid.UUID]:
        return {
            self.title.nodegroup_id,
            self.carrier.nodegroup_id,
            self.external_media.nodegroup_id,
        }


def carrier_file_id_from_tile(tile: TileModel, gmap: GraphMap) -> str:
    data = tile.data or {}
    return i18n_plain(data.get(str(gmap.file_id.nodeid)))


def existing_ir_by_legacy(gmap: GraphMap) -> dict[str, ResourceInstance]:
    rows = ResourceInstance.objects.filter(legacyid__startswith=LEGACY_PREFIX)
    found = {}
    for row in rows:
        if row.graph_id != gmap.ir.graphid:
            raise SystemExit(
                f"ERROR: legacyid {row.legacyid} exists on graph {row.graph_id}, "
                f"not Information Resource Model"
            )
        found[row.legacyid] = row
    return found


def existing_carrier_tiles(gmap: GraphMap, ir: ResourceInstance) -> list[TileModel]:
    return list(
        TileModel.objects.filter(
            resourceinstance=ir, nodegroup_id=gmap.carrier.nodegroup_id
        )
    )


def place_has_ir_link(gmap: GraphMap, place: ResourceInstance, ir_id: uuid.UUID) -> bool:
    ir_s = str(ir_id)
    tiles = TileModel.objects.filter(
        resourceinstance=place, nodegroup_id=gmap.external_media.nodegroup_id
    )
    for tile in tiles:
        rels = (tile.data or {}).get(str(gmap.external_media.nodeid)) or []
        if not isinstance(rels, list):
            rels = [rels]
        for rel in rels:
            if isinstance(rel, dict) and str(rel.get("resourceId")) == ir_s:
                return True
    return False


def resolve_places(
    links: list[tuple[str, str]], gmap: GraphMap
) -> tuple[dict[str, ResourceInstance], list[str], list[str]]:
    site_ids = sorted({site_id for site_id, _ in links})
    rows = ResourceInstance.objects.filter(
        graph_id=gmap.place.graphid, legacyid__in=site_ids
    )
    by_legacy = {}
    ambiguous = []
    for row in rows:
        if row.legacyid in by_legacy:
            ambiguous.append(row.legacyid)
        else:
            by_legacy[row.legacyid] = row
    unresolved = [sid for sid in site_ids if sid not in by_legacy]
    # A legacyid on a non-Place graph would not appear here; check collisions.
    collisions = list(
        ResourceInstance.objects.filter(legacyid__in=site_ids)
        .exclude(graph_id=gmap.place.graphid)
        .values_list("legacyid", flat=True)
    )
    if collisions:
        ambiguous.extend(collisions)
    return by_legacy, unresolved, sorted(set(ambiguous))


def snapshot(gmap: GraphMap) -> dict:
    place_ids = set(
        TileModel.objects.filter(
            resourceinstance__graph_id=gmap.place.graphid
        ).values_list("tileid", flat=True)
    )
    return {
        "place_tile_ids": place_ids,
        "place_tile_count": len(place_ids),
        "assessment_ir": TileModel.objects.filter(
            nodegroup_id=gmap.assessment_ir.nodegroup_id
        ).count(),
        "file_list": TileModel.objects.filter(
            nodegroup_id=gmap.forbidden_information_carrier.nodegroup_id
        ).count(),
        "publication": TileModel.objects.filter(
            nodegroup_id=gmap.forbidden_publication.nodegroup_id
        ).count(),
        "external_xref": TileModel.objects.filter(
            nodegroup_id=gmap.forbidden_external_xref.nodegroup_id
        ).count(),
        "rxr": _rxr_count(),
        "ir_count": ResourceInstance.objects.filter(graph_id=gmap.ir.graphid).count(),
    }


def _rxr_count() -> int:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM resource_x_resource")
        return cursor.fetchone()[0]


def plan_counts(
    files_by_id: dict[str, dict],
    links: list[tuple[str, str]],
    places: dict[str, ResourceInstance],
    irs: dict[str, ResourceInstance],
    gmap: GraphMap,
) -> dict:
    new_irs = []
    existing_irs = []
    new_carriers = []
    existing_carriers = []
    new_rels = []
    existing_rels = []
    errors = []

    for drive_id, meta in sorted(files_by_id.items()):
        legacy = meta["legacyid"]
        ir = irs.get(legacy)
        if ir is None:
            new_irs.append(drive_id)
            new_carriers.append(drive_id)
            continue
        existing_irs.append(drive_id)
        carriers = existing_carrier_tiles(gmap, ir)
        matching = [
            t for t in carriers if carrier_file_id_from_tile(t, gmap) == drive_id
        ]
        if matching:
            existing_carriers.append(drive_id)
        elif carriers:
            errors.append(
                f"{legacy} exists but carrier file_id does not match {drive_id}; "
                "will not overwrite"
            )
        else:
            new_carriers.append(drive_id)

    unresolved_links = []
    for site_id, drive_id in links:
        place = places.get(site_id)
        if place is None:
            unresolved_links.append((site_id, drive_id))
            continue
        ir = irs.get(f"{LEGACY_PREFIX}{drive_id}")
        ir_id = ir.resourceinstanceid if ir is not None else None
        if ir_id is not None and place_has_ir_link(gmap, place, ir_id):
            existing_rels.append((site_id, drive_id))
        else:
            new_rels.append((site_id, drive_id))

    return {
        "new_irs": new_irs,
        "existing_irs": existing_irs,
        "new_carriers": new_carriers,
        "existing_carriers": existing_carriers,
        "new_rels": new_rels,
        "existing_rels": existing_rels,
        "unresolved_links": unresolved_links,
        "errors": errors,
    }


def print_report(title: str, stats: dict) -> None:
    print(title)
    order = [
        ("UNIQUE DRIVE FILES", "unique_drive_files"),
        ("PLACE LINKS", "place_links"),
        ("NEW INFORMATION RESOURCES", "new_irs"),
        ("EXISTING INFORMATION RESOURCES", "existing_irs"),
        ("NEW CARRIER TILES", "new_carriers"),
        ("EXISTING CARRIER TILES", "existing_carriers"),
        ("NEW PLACE↔IR RELATIONSHIPS", "new_rels"),
        ("EXISTING RELATIONSHIPS", "existing_rels"),
        ("SKIPPED REVIEW/NONE", "skipped_review_none"),
        ("UNRESOLVED PLACES", "unresolved_places"),
        ("ERRORS", "errors"),
    ]
    for label, key in order:
        val = stats[key]
        if isinstance(val, list):
            print(f"  {label}: {len(val)}")
            for item in val[:20]:
                print(f"    - {item}")
            if len(val) > 20:
                print(f"    ... {len(val) - 20} more")
        else:
            print(f"  {label}: {val}")


def ensure_ir_graph_active(gmap: GraphMap) -> None:
    if not gmap.ir.is_active:
        GraphModel.objects.filter(pk=gmap.ir.pk).update(is_active=True)
        print(f"activated graph {IR_SLUG}")


def make_title_tile(gmap: GraphMap, filename: str) -> Tile:
    tile = Tile()
    tile.tileid = uuid.uuid4()
    tile.nodegroup_id = gmap.title.nodegroup_id
    tile.data = {str(gmap.title.nodeid): i18n(filename)}
    return tile


def make_carrier_tile(gmap: GraphMap, file_id: str, filename: str) -> Tile:
    tile = Tile()
    tile.tileid = uuid.uuid4()
    tile.nodegroup_id = gmap.carrier.nodegroup_id
    tile.data = {
        str(gmap.file_id.nodeid): i18n(file_id),
        str(gmap.storage.nodeid): [gmap.storage_value],
        str(gmap.mime.nodeid): i18n(MIME_PDF),
        str(gmap.caption.nodeid): i18n(filename),
    }
    return tile


def make_media_tile(gmap: GraphMap, ir_id: uuid.UUID) -> Tile:
    tile = Tile()
    tile.tileid = uuid.uuid4()
    tile.nodegroup_id = gmap.external_media.nodegroup_id
    tile.data = {
        str(gmap.external_media.nodeid): [
            {
                "resourceId": str(ir_id),
                "ontologyProperty": P129I,
                "inverseOntologyProperty": P129,
            }
        ]
    }
    return tile


def assert_allowed_tile(gmap: GraphMap, tile: Tile, context: str) -> None:
    if tile.nodegroup_id not in gmap.allowed_nodegroups:
        raise RuntimeError(
            f"refusing to write nodegroup {tile.nodegroup_id} ({context})"
        )


def create_ir(gmap: GraphMap, meta: dict) -> Resource:
    resource = Resource(graph_id=gmap.ir.graphid, legacyid=meta["legacyid"])
    title = make_title_tile(gmap, meta["filename"])
    carrier = make_carrier_tile(gmap, meta["file_id"], meta["filename"])
    assert_allowed_tile(gmap, title, "IR title")
    assert_allowed_tile(gmap, carrier, "IR carrier")
    resource.tiles = [title, carrier]
    resource.save(index=False, user=gmap.user)
    return resource


def add_carrier(gmap: GraphMap, ir: ResourceInstance, meta: dict) -> None:
    resource = Resource.objects.get(pk=ir.pk)
    tile = make_carrier_tile(gmap, meta["file_id"], meta["filename"])
    assert_allowed_tile(gmap, tile, "IR carrier")
    tile.resourceinstance = resource
    tile.save(index=False, user=gmap.user)


def add_place_link(gmap: GraphMap, place: ResourceInstance, ir_id: uuid.UUID) -> None:
    tile = make_media_tile(gmap, ir_id)
    assert_allowed_tile(gmap, tile, "Place external_media")
    tile.resourceinstance = Resource.objects.get(pk=place.pk)
    tile.save(index=False, user=gmap.user)


def apply_plan(gmap: GraphMap, files_by_id: dict, plan: dict, places: dict) -> dict:
    created_irs = 0
    reused_irs = 0
    created_carriers = 0
    reused_carriers = 0
    created_rels = 0
    reused_rels = 0
    errors = []

    ir_ids: dict[str, uuid.UUID] = {}
    existing = existing_ir_by_legacy(gmap)
    for drive_id, meta in sorted(files_by_id.items()):
        ir = existing.get(meta["legacyid"])
        try:
            with transaction.atomic():
                if ir is None:
                    resource = create_ir(gmap, meta)
                    ir_ids[drive_id] = resource.resourceinstanceid
                    created_irs += 1
                    created_carriers += 1
                else:
                    ir_ids[drive_id] = ir.resourceinstanceid
                    reused_irs += 1
                    if drive_id in plan["new_carriers"]:
                        add_carrier(gmap, ir, meta)
                        created_carriers += 1
                    else:
                        reused_carriers += 1
        except Exception as exc:
            errors.append(f"IR {meta['legacyid']}: {exc}")

    for site_id, drive_id in plan["existing_rels"]:
        reused_rels += 1

    for site_id, drive_id in plan["new_rels"]:
        place = places.get(site_id)
        ir_id = ir_ids.get(drive_id)
        if place is None or ir_id is None:
            errors.append(f"link {site_id} → {drive_id}: missing Place or IR")
            continue
        try:
            with transaction.atomic():
                if place_has_ir_link(gmap, place, ir_id):
                    reused_rels += 1
                    continue
                add_place_link(gmap, place, ir_id)
                created_rels += 1
        except Exception as exc:
            errors.append(f"link {site_id} → {drive_id}: {exc}")

    return {
        "created_irs": created_irs,
        "reused_irs": reused_irs,
        "created_carriers": created_carriers,
        "reused_carriers": reused_carriers,
        "created_rels": created_rels,
        "reused_rels": reused_rels,
        "errors": errors,
        "ir_ids": ir_ids,
    }


def validate_after(gmap: GraphMap, files_by_id: dict, links: list, before: dict) -> list[str]:
    problems = []
    irs = existing_ir_by_legacy(gmap)
    phase_ids = {meta["legacyid"] for meta in files_by_id.values()}
    found = [legacy for legacy in phase_ids if legacy in irs]
    extra = [legacy for legacy in irs if legacy not in phase_ids]
    if len(found) != EXPECTED_PDFS:
        problems.append(
            f"expected {EXPECTED_PDFS} gdrive: IRs for phase 1, found {len(found)}"
        )
    if extra:
        problems.append(f"unexpected extra gdrive: IRs: {extra}")

    for drive_id, meta in files_by_id.items():
        ir = irs.get(meta["legacyid"])
        if ir is None:
            problems.append(f"missing IR {meta['legacyid']}")
            continue
        carriers = existing_carrier_tiles(gmap, ir)
        if len(carriers) != 1:
            problems.append(f"{meta['legacyid']} carrier tiles={len(carriers)} (expected 1)")
            continue
        data = carriers[0].data or {}
        file_id = i18n_plain(data.get(str(gmap.file_id.nodeid)))
        mime = i18n_plain(data.get(str(gmap.mime.nodeid)))
        storage_vals = data.get(str(gmap.storage.nodeid)) or []
        labels = []
        for item in storage_vals:
            for label in item.get("labels") or []:
                if label.get("valuetype_id") == "prefLabel":
                    labels.append(label.get("value"))
        if file_id != drive_id:
            problems.append(f"{meta['legacyid']} file_id={file_id!r}")
        if mime != MIME_PDF:
            problems.append(f"{meta['legacyid']} mime_type={mime!r}")
        if STORAGE_ITEM_LABEL not in labels:
            problems.append(f"{meta['legacyid']} storage_backend labels={labels}")

    places, unresolved, ambiguous = resolve_places(links, gmap)
    if unresolved or ambiguous:
        problems.append(f"unresolved={unresolved} ambiguous={ambiguous}")

    rel_count = 0
    duplicates = 0
    for site_id, drive_id in links:
        place = places.get(site_id)
        ir = irs.get(f"{LEGACY_PREFIX}{drive_id}")
        if place is None or ir is None:
            continue
        tiles = list(
            TileModel.objects.filter(
                resourceinstance=place, nodegroup_id=gmap.external_media.nodegroup_id
            )
        )
        hits = 0
        for tile in tiles:
            rels = (tile.data or {}).get(str(gmap.external_media.nodeid)) or []
            if not isinstance(rels, list):
                rels = [rels]
            for rel in rels:
                if isinstance(rel, dict) and str(rel.get("resourceId")) == str(
                    ir.resourceinstanceid
                ):
                    hits += 1
        if hits == 1:
            rel_count += 1
        elif hits > 1:
            duplicates += 1
            problems.append(f"duplicate Place↔IR tiles for {site_id} → {drive_id}")
        else:
            problems.append(f"missing Place↔IR tile for {site_id} → {drive_id}")
    if rel_count != EXPECTED_LINKS:
        problems.append(f"Place↔IR relationships={rel_count}, expected {EXPECTED_LINKS}")

    after = snapshot(gmap)
    if after["assessment_ir"] != before["assessment_ir"]:
        problems.append("assessment P16 tile count changed")
    if after["file_list"] != before["file_list"]:
        problems.append("file-list tile count changed")
    if after["publication"] != before["publication"]:
        problems.append("publication tile count changed")
    if after["external_xref"] != before["external_xref"]:
        problems.append("external_xref tile count changed")
    missing_place_tiles = before["place_tile_ids"] - after["place_tile_ids"]
    if missing_place_tiles:
        problems.append(f"{len(missing_place_tiles)} Place tiles were deleted")

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM resource_x_resource
            WHERE nodeid = %s
              AND resourceinstancefrom_graphid = %s
              AND resourceinstanceto_graphid = %s
            """,
            [str(gmap.external_media.nodeid), str(gmap.place.graphid), str(gmap.ir.graphid)],
        )
        rxr_media = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM resource_x_resource WHERE nodeid = %s",
            [str(gmap.assessment_ir.nodeid)],
        )
        rxr_assessment = cursor.fetchone()[0]
    if rxr_media != EXPECTED_LINKS:
        problems.append(
            f"resource_x_resource on external_media={rxr_media}, expected {EXPECTED_LINKS}"
        )
    if rxr_assessment != 0:
        problems.append(f"assessment resource_x_resource count={rxr_assessment}")
    if duplicates:
        problems.append(f"duplicate relationships={duplicates}")

    return problems


def index_graphs(gmap: GraphMap) -> str:
    try:
        from django.core import management

        management.call_command(
            "es",
            "index_resources_by_type",
            resource_types=f"{gmap.ir.graphid},{gmap.place.graphid}",
            verbosity=1,
        )
        return "ok"
    except Exception as exc:
        return f"index failed (postgres data already written): {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Drive bibliography PDFs as Arches external media (phase 1)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write Information Resources and Place relationships. Default is dry-run.",
    )
    args = parser.parse_args()

    allowed, skipped_ids, skipped_rows = load_matches()
    files_by_id, links, extras = load_bibliography_links(allowed, skipped_ids)
    gmap = GraphMap()

    if extras["unmatched_drive_ids"]:
        gmap.errors.append(
            "BIBLIOGRAPHY Drive IDs not in exact/high matches: "
            + ", ".join(extras["unmatched_drive_ids"])
        )
    if extras["empty_site_id"]:
        gmap.errors.append(
            f"{extras['empty_site_id']} BIBLIOGRAPHY Drive IDs had empty SITE_SOURCE_ID"
        )
    missing_names = [
        drive_id for drive_id, meta in files_by_id.items() if not meta["filename"]
    ]
    if missing_names:
        gmap.errors.append(f"Drive IDs missing filename: {missing_names}")

    irs = existing_ir_by_legacy(gmap)
    places, unresolved, ambiguous = resolve_places(links, gmap)
    if ambiguous:
        gmap.errors.append(f"ambiguous Place identities: {ambiguous}")

    plan = plan_counts(files_by_id, links, places, irs, gmap)
    plan["errors"].extend(gmap.errors)

    stats = {
        "unique_drive_files": len(files_by_id),
        "place_links": len(links),
        "new_irs": plan["new_irs"],
        "existing_irs": plan["existing_irs"],
        "new_carriers": plan["new_carriers"],
        "existing_carriers": plan["existing_carriers"],
        "new_rels": plan["new_rels"],
        "existing_rels": plan["existing_rels"],
        "skipped_review_none": (
            f"{len(skipped_ids)} unique Drive IDs / {skipped_rows} match rows; "
            f"{extras['skipped_review_bibliography']} bibliography occurrences"
        ),
        "unresolved_places": unresolved,
        "errors": plan["errors"],
    }
    mode = "APPLY" if args.apply else "DRY-RUN"
    print_report(f"=== {mode} PHASE 1 EXTERNAL MEDIA ===", stats)
    print(f"  csv_files={extras['csv_files']}")
    print(f"  title node={gmap.title.nodeid}")
    print(f"  carrier nodegroup={gmap.carrier.nodeid}")
    print(f"  file_id node={gmap.file_id.nodeid}")
    print(f"  storage_backend node={gmap.storage.nodeid}")
    print(f"  mime_type node={gmap.mime.nodeid}")
    print(f"  external_media node={gmap.external_media.nodeid}")
    print(f"  IR graph={gmap.ir.graphid}")
    print(f"  Place graph={gmap.place.graphid}")
    print(f"  assessment P16 node={gmap.assessment_ir.nodeid} (will not write)")

    preflight_ok = (
        len(files_by_id) == EXPECTED_PDFS
        and len(links) == EXPECTED_LINKS
        and not unresolved
        and not ambiguous
        and not plan["errors"]
        and extras["skipped_review_bibliography"] == 0
        and not extras["unmatched_drive_ids"]
    )
    if not preflight_ok:
        print("PREFLIGHT FAILED — refusing to apply.")
        if args.apply:
            return 2
        return 1

    print("PREFLIGHT OK: 9 PDFs, 129 Place links, 0 unresolved, 0 review/none in source.")
    if not args.apply:
        print("No database writes. Re-run with --apply to import.")
        return 0

    before = snapshot(gmap)
    print(
        "BASELINE "
        f"place_tiles={before['place_tile_count']} "
        f"assessment_ir={before['assessment_ir']} "
        f"file_list={before['file_list']} "
        f"publication={before['publication']} "
        f"external_xref={before['external_xref']} "
        f"rxr={before['rxr']} "
        f"ir={before['ir_count']}"
    )
    ensure_ir_graph_active(gmap)
    result = apply_plan(gmap, files_by_id, plan, places)
    print("=== APPLY RESULT ===")
    print(f"  new IR resources: {result['created_irs']}")
    print(f"  reused IR resources: {result['reused_irs']}")
    print(f"  carrier tiles created: {result['created_carriers']}")
    print(f"  carrier tiles reused: {result['reused_carriers']}")
    print(f"  Place↔IR created: {result['created_rels']}")
    print(f"  Place↔IR reused: {result['reused_rels']}")
    if result["errors"]:
        print("  APPLY ERRORS:")
        for err in result["errors"]:
            print(f"    - {err}")

    problems = validate_after(gmap, files_by_id, links, before)
    print("=== VALIDATION ===")
    if problems:
        for problem in problems:
            print(f"  FAIL {problem}")
    else:
        print("  PASS 9 IRs, 129 Place↔IR links, no forbidden-node writes, no deleted Place tiles")

    print("indexing elasticsearch...")
    print("  " + index_graphs(gmap))
    return 1 if (result["errors"] or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
