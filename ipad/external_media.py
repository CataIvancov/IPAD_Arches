"""Presentation helpers for Place → External Media Drive PDFs.

Does not write tiles or alter the CIDOC graph. File IDs stay opaque; Drive
preview URLs are generated only in the frontend/API response, never stored.
"""

from __future__ import annotations

import re
import uuid

from arches.app.models.graph import Graph
from arches.app.models.models import Node, ResourceInstance, ResourceXResource, TileModel

PLACE_SLUG = "ipad_place_site_archeology"
IR_SLUG = "information_resource_model"

EXTERNAL_MEDIA_ALIAS = "external_media"
CARRIER_ALIAS = "external_information_carrier"
FILE_ID_ALIAS = "external_carrier_file_id"
STORAGE_ALIAS = "storage_backend"
MIME_ALIAS = "mime_type"
CAPTION_ALIAS = "caption"

EXPECTED_PLACE_GRAPHID = uuid.UUID("de49aafc-dfa5-11ef-8d94-3565fe170f74")
EXPECTED_IR_GRAPHID = uuid.UUID("3caf329f-b8f7-11e6-84a5-026d961c88e6")
EXPECTED_EXTERNAL_MEDIA = uuid.UUID("7d09bbdb-46de-4ca0-aeae-8dd385c25c80")
EXPECTED_CARRIER = uuid.UUID("b1f2c491-8982-4527-8dc7-015981595ee0")
EXPECTED_FILE_ID = uuid.UUID("bf680d0a-0a9c-439e-a0ba-120798f4b1c4")
EXPECTED_STORAGE = uuid.UUID("5b0aaf6d-ba45-472f-b171-73574800353e")
EXPECTED_MIME = uuid.UUID("efd29981-f114-4002-8dbb-ef5f6ab7aea7")
EXPECTED_CAPTION = uuid.UUID("73640e9c-2255-4437-b00c-02588b0a78c9")

DRIVE_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{25,128}$")
GOOGLE_DRIVE = "google_drive"
GOOGLE_DRIVE_ITEM_ID = uuid.UUID("da89209c-430d-4a99-aa67-ea4c1774d29e")
MIME_PDF = "application/pdf"


class ExternalMediaConfigError(RuntimeError):
    pass


def source_graph(slug: str) -> Graph:
    graph = Graph.objects.filter(slug=slug, source_identifier__isnull=True).first()
    if graph is None:
        raise ExternalMediaConfigError(f"graph slug={slug} not found")
    return graph


def node_by_alias(graph: Graph, alias: str) -> Node:
    nodes = list(Node.objects.filter(graph=graph, alias=alias))
    if len(nodes) != 1:
        raise ExternalMediaConfigError(
            f"expected one node alias={alias} on {graph.slug}, found {len(nodes)}"
        )
    return nodes[0]


def i18n_plain(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "raw_value"):
        raw = getattr(value, "raw_value")
        if isinstance(raw, dict):
            return i18n_plain(raw)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("en",):
            inner = value.get(key)
            if isinstance(inner, dict) and inner.get("value"):
                return str(inner["value"]).strip()
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        for inner in value.values():
            if inner is None:
                continue
            if isinstance(inner, dict) and inner.get("value"):
                return str(inner["value"]).strip()
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return ""
    return str(value).strip()


def normalize_drive_file_id(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if any(ch in text for ch in "/:?#.&%<>\"'\\"):
        return None
    if not DRIVE_FILE_ID_RE.fullmatch(text):
        return None
    return text


def storage_backend_label(value) -> str:
    items = value if isinstance(value, list) else [value]
    for item in items:
        if not isinstance(item, dict):
            continue
        for label in item.get("labels") or []:
            if not isinstance(label, dict):
                continue
            if label.get("valuetype_id") == "prefLabel" and label.get("value"):
                return str(label["value"]).strip()
        uri = str(item.get("uri") or "")
        if GOOGLE_DRIVE in uri.lower():
            return GOOGLE_DRIVE
        for key in ("list_item_id", "id"):
            raw = item.get(key)
            try:
                if raw and uuid.UUID(str(raw)) == GOOGLE_DRIVE_ITEM_ID:
                    return GOOGLE_DRIVE
            except (ValueError, TypeError, AttributeError):
                continue
    return ""


class ExternalMediaGraph:
    def __init__(self):
        self.place = source_graph(PLACE_SLUG)
        self.ir = source_graph(IR_SLUG)
        if self.place.graphid != EXPECTED_PLACE_GRAPHID:
            raise ExternalMediaConfigError("unexpected Place graphid")
        if self.ir.graphid != EXPECTED_IR_GRAPHID:
            raise ExternalMediaConfigError("unexpected Information Resource graphid")

        self.external_media = node_by_alias(self.place, EXTERNAL_MEDIA_ALIAS)
        self.carrier = node_by_alias(self.ir, CARRIER_ALIAS)
        self.file_id = node_by_alias(self.ir, FILE_ID_ALIAS)
        self.storage = node_by_alias(self.ir, STORAGE_ALIAS)
        self.mime = node_by_alias(self.ir, MIME_ALIAS)
        self.caption = node_by_alias(self.ir, CAPTION_ALIAS)

        expected = {
            self.external_media: EXPECTED_EXTERNAL_MEDIA,
            self.carrier: EXPECTED_CARRIER,
            self.file_id: EXPECTED_FILE_ID,
            self.storage: EXPECTED_STORAGE,
            self.mime: EXPECTED_MIME,
            self.caption: EXPECTED_CAPTION,
        }
        for node, expected_id in expected.items():
            if node.nodeid != expected_id:
                raise ExternalMediaConfigError(
                    f"node {node.alias} is {node.nodeid}, expected {expected_id}"
                )


def resource_title(resource: ResourceInstance) -> str:
    name = i18n_plain(resource.name)
    if name:
        return name
    descriptors = resource.descriptors or {}
    if isinstance(descriptors, dict):
        for lang in ("en",):
            block = descriptors.get(lang) or {}
            if isinstance(block, dict):
                name = i18n_plain(block.get("name") or block.get("displayname"))
                if name:
                    return name
        for block in descriptors.values():
            if isinstance(block, dict):
                name = i18n_plain(block.get("name") or block.get("displayname"))
                if name:
                    return name
    return ""


def carrier_items_for_ir(gmap: ExternalMediaGraph, ir: ResourceInstance) -> list[dict]:
    tiles = TileModel.objects.filter(
        resourceinstance=ir, nodegroup_id=gmap.carrier.nodegroup_id
    )
    items = []
    for tile in tiles:
        data = tile.data or {}
        file_id = normalize_drive_file_id(
            i18n_plain(data.get(str(gmap.file_id.nodeid)))
        )
        storage = storage_backend_label(data.get(str(gmap.storage.nodeid))).lower()
        mime = i18n_plain(data.get(str(gmap.mime.nodeid))).lower()
        if file_id is None or storage != GOOGLE_DRIVE or mime != MIME_PDF:
            continue
        caption = i18n_plain(data.get(str(gmap.caption.nodeid)))
        title = resource_title(ir) or caption
        if not title:
            continue
        items.append(
            {
                "resource_id": str(ir.pk),
                "title": title,
                "file_id": file_id,
                "storage_backend": GOOGLE_DRIVE,
                "mime_type": MIME_PDF,
                "caption": caption,
            }
        )
    return items


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def related_ir_ids_from_place_tiles(gmap: ExternalMediaGraph, place: ResourceInstance) -> list[uuid.UUID]:
    tiles = TileModel.objects.filter(
        resourceinstance=place,
        nodegroup_id=gmap.external_media.nodegroup_id,
    ).order_by("sortorder")
    ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for tile in tiles:
        values = (tile.data or {}).get(str(gmap.external_media.nodeid)) or []
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            rid = _as_uuid(item.get("resourceId") or item.get("resourceid"))
            if rid is None or rid in seen:
                continue
            seen.add(rid)
            ids.append(rid)
    return ids


def related_ir_ids_from_resource_x_resource(
    gmap: ExternalMediaGraph, place: ResourceInstance
) -> list[uuid.UUID]:
    relations = ResourceXResource.objects.filter(
        from_resource=place,
        node_id=gmap.external_media.nodeid,
        to_resource__graph_id=gmap.ir.graphid,
    ).order_by("created")
    ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for relation in relations:
        rid = relation.to_resource_id
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        ids.append(rid)
    return ids


def list_place_drive_pdfs(place: ResourceInstance) -> list[dict]:
    gmap = ExternalMediaGraph()
    if place.graph_id != gmap.place.graphid:
        return []

    ir_ids = related_ir_ids_from_place_tiles(gmap, place)
    if not ir_ids:
        ir_ids = related_ir_ids_from_resource_x_resource(gmap, place)

    resources = {
        resource.pk: resource
        for resource in ResourceInstance.objects.filter(
            pk__in=ir_ids, graph_id=gmap.ir.graphid
        )
    }

    items = []
    for ir_id in ir_ids:
        ir = resources.get(ir_id)
        if ir is None:
            continue
        items.extend(carrier_items_for_ir(gmap, ir))
    return items
