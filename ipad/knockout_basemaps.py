"""Inject settings.BASEMAPS into Knockout map bootstrap (no map_layers rows)."""

import json
import os
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

from django.conf import settings


def inject_settings_basemaps(context):
    map_layers = list(context.get("map_layers") or [])
    map_sources = list(context.get("map_sources") or [])
    extra_layers, extra_sources = build_settings_knockout_basemaps(
        map_layers, map_sources
    )
    if extra_layers:
        context["map_layers"] = map_layers + extra_layers
    if extra_sources:
        context["map_sources"] = map_sources + extra_sources
    return context


def build_settings_knockout_basemaps(existing_layers, existing_sources):
    existing_layer_names = {
        getattr(layer, "name", None) for layer in existing_layers
    }
    existing_layer_names.discard(None)
    existing_source_names = {
        getattr(source, "name", None) for source in existing_sources
    }
    existing_source_names.discard(None)

    extra_layers = []
    extra_sources = []
    added_source_names = set()

    for entry in getattr(settings, "BASEMAPS", []) or []:
        vue_name = entry.get("name")
        title = entry.get("title") or vue_name
        if not vue_name or not title:
            continue
        if vue_name in existing_layer_names or title in existing_layer_names:
            continue

        style = _load_local_style(entry.get("url"))
        if not style:
            continue

        style_sources = style.get("sources") or {}
        style_layers = style.get("layers")
        if not style_sources or not style_layers:
            continue

        skipped_existing_source = False
        for source_name, source_spec in style_sources.items():
            if source_name in existing_source_names:
                skipped_existing_source = True
                break
            if source_name in added_source_names:
                continue
            extra_sources.append(
                SimpleNamespace(
                    name=source_name,
                    source_json=json.dumps(source_spec),
                )
            )
            added_source_names.add(source_name)

        if skipped_existing_source:
            continue

        extra_layers.append(
            SimpleNamespace(
                maplayerid=uuid.uuid5(
                    uuid.NAMESPACE_URL, "ipad-knockout-basemap:" + vue_name
                ),
                name=title,
                layer_json=json.dumps(style_layers),
                isoverlay=False,
                icon="fa fa-globe",
                legend=None,
                searchonly=False,
                activated=True,
                addtomap=bool(entry.get("addtomap", False)),
                centerx=None,
                centery=None,
                zoom=None,
                sortorder=100,
                ispublic=True,
            )
        )

    return extra_layers, extra_sources


def _load_local_style(url):
    if not url:
        return None
    filename = os.path.basename(urlparse(url).path)
    if not filename or not filename.endswith(".json"):
        return None
    app_root = getattr(settings, "APP_ROOT", "")
    candidates = [
        os.path.join(app_root, "media", "map-styles", filename),
        os.path.join(app_root, "staticfiles", "map-styles", filename),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    return None
