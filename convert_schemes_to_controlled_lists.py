#!/usr/bin/env python
"""One-off: convert RDM ConceptSchemes to controlled lists.

Does not create SKOS Collections. Idempotent: skip a scheme if a list
already exists with the same id or name. Skip empty schemes (Candidates).

Usage:
    cd /opt/ipad/ipad && /opt/ipad/envs-arches/bin/python convert_schemes_to_controlled_lists.py
"""
import os
import sys
import uuid
from collections import defaultdict, deque

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ipad.settings")

import django

django.setup()

from django.db import transaction
from django.db.models import Q

from arches.app.models.models import Concept, DValueType, Relation, Value
from arches_controlled_lists.models import List, ListItem, ListItemValue

SKIP_SCHEME_NAMES = {"Candidates"}
PREFERRED_SORT_LANGUAGE = "en"
HOST = "http://localhost:8000/plugins/controlled-list-manager/item/"


def scheme_label(scheme):
    labels = list(
        Value.objects.filter(concept=scheme, valuetype_id="prefLabel").values_list(
            "language_id", "value"
        )
    )
    by_lang = {lang: val for lang, val in labels}
    for code in (PREFERRED_SORT_LANGUAGE, "en-US", "en"):
        if code in by_lang:
            return by_lang[code]
    return labels[0][1] if labels else str(scheme.pk)


def best_preflabel(concept_id, values_by_concept):
    ranked = []
    for v in values_by_concept.get(concept_id, []):
        if v.valuetype_id != "prefLabel":
            continue
        rank = 0 if v.language_id == PREFERRED_SORT_LANGUAGE else 1
        ranked.append((rank, (v.value or "").lower(), v.value or ""))
    ranked.sort()
    return ranked[0][2] if ranked else ""


def convert_scheme(scheme):
    name = scheme_label(scheme)
    if name in SKIP_SCHEME_NAMES:
        print(f"SKIP empty/staging scheme {name!r}")
        return None

    existing = List.objects.filter(Q(pk=scheme.pk) | Q(name=name)).first()
    if existing:
        print(
            f"SKIP existing list {existing.name!r} id={existing.pk} "
            f"items={existing.list_items.count()}"
        )
        return existing

    narrower_children = defaultdict(list)
    narrower_parents = defaultdict(list)
    for frm, to in Relation.objects.filter(relationtype="narrower").values_list(
        "conceptfrom_id", "conceptto_id"
    ):
        narrower_children[frm].append(to)
        narrower_parents[to].append(frm)

    tops = list(
        Relation.objects.filter(
            conceptfrom=scheme, relationtype="hasTopConcept"
        ).values_list("conceptto_id", flat=True)
    )
    if not tops:
        print(f"SKIP scheme {name!r}: no top concepts")
        return None

    descendants = set()
    queue = deque(tops)
    while queue:
        cid = queue.popleft()
        if cid in descendants:
            continue
        descendants.add(cid)
        for child in narrower_children.get(cid, []):
            if child not in descendants:
                queue.append(child)

    values_by_concept = defaultdict(list)
    note_or_label = set(
        DValueType.objects.filter(category__in=["note", "label"]).values_list(
            "valuetype", flat=True
        )
    )
    for val in Value.objects.filter(concept_id__in=descendants):
        values_by_concept[val.concept_id].append(val)

    # Primary parent: first in-scheme narrower parent; extras = polyhierarchy.
    primary_parent = {}
    extra_parents = defaultdict(list)
    for cid in descendants:
        in_scheme_parents = [
            p for p in narrower_parents.get(cid, []) if p in descendants
        ]
        if not in_scheme_parents:
            primary_parent[cid] = None
        else:
            primary_parent[cid] = in_scheme_parents[0]
            extra_parents[cid] = in_scheme_parents[1:]

    sibling_groups = defaultdict(list)
    for cid in descendants:
        sibling_groups[primary_parent[cid]].append(cid)

    sortorder_map = {}
    for parent_id, siblings in sibling_groups.items():
        decorated = []
        for cid in siblings:
            so = None
            for val in values_by_concept.get(cid, []):
                if val.valuetype_id == "sortorder":
                    try:
                        so = int(val.value)
                    except (TypeError, ValueError):
                        so = None
                    break
            decorated.append((so is None, so or 0, best_preflabel(cid, values_by_concept).lower(), cid))
        decorated.sort()
        for i, row in enumerate(decorated):
            sortorder_map[row[3]] = i

    def uri_for(cid, item_id):
        for val in values_by_concept.get(cid, []):
            if val.valuetype_id == "identifier" and val.value:
                return val.value
        return f"{HOST.rstrip('/')}/{item_id}"

    def guide_for(cid):
        for val in values_by_concept.get(cid, []):
            if val.valuetype_id == "collector":
                return True
        return False

    list_obj = List(id=scheme.pk, name=name, dynamic=False, searchable=False)
    items = {}
    item_values = []

    for cid in descendants:
        item = ListItem(
            id=cid,
            uri=uri_for(cid, cid),
            list=list_obj,
            sortorder=sortorder_map[cid],
            parent=None,
            guide=guide_for(cid),
        )
        items[cid] = item

        seen_pref_lang = set()
        seen_tuple = set()
        for val in values_by_concept.get(cid, []):
            if val.valuetype_id not in note_or_label:
                continue
            valuetype = val.valuetype_id
            lang = val.language_id
            text = val.value or ""
            if valuetype == "prefLabel":
                if lang in seen_pref_lang:
                    continue
                seen_pref_lang.add(lang)
            key = (valuetype, lang, text)
            if key in seen_tuple:
                continue
            seen_tuple.add(key)
            item_values.append(
                ListItemValue(
                    list_item=item,
                    valuetype_id=valuetype,
                    language_id=lang,
                    value=text,
                )
            )

    duplicates = []
    duplicate_values = []
    for cid, parents in extra_parents.items():
        source = items[cid]
        for parent_cid in parents:
            parent_item = items[parent_cid]
            siblings = [
                it
                for it in list(items.values()) + duplicates
                if it.parent_id == parent_item.id or it.parent is parent_item
            ]
            max_so = max((s.sortorder for s in siblings), default=-1)
            new_item = ListItem(
                id=uuid.uuid4(),
                uri=source.uri,
                list=list_obj,
                sortorder=max_so + 1,
                parent=parent_item,
                guide=source.guide,
            )
            duplicates.append(new_item)
            for liv in item_values:
                if liv.list_item is source:
                    duplicate_values.append(
                        ListItemValue(
                            list_item=new_item,
                            valuetype_id=liv.valuetype_id,
                            language_id=liv.language_id,
                            value=liv.value,
                        )
                    )

    with transaction.atomic():
        list_obj.save()
        ListItem.objects.bulk_create(items.values())
        to_update = []
        for cid, item in items.items():
            parent_cid = primary_parent[cid]
            if parent_cid is not None:
                item.parent = items[parent_cid]
                to_update.append(item)
        if to_update:
            ListItem.objects.bulk_update(to_update, ["parent"])
        if duplicates:
            ListItem.objects.bulk_create(duplicates)
        ListItemValue.objects.bulk_create(item_values + duplicate_values)

    total_items = ListItem.objects.filter(list=list_obj).count()
    extra_n = len(duplicates)
    print(
        f"CREATED list {name!r} id={list_obj.pk} items={total_items} "
        f"(scheme concepts={len(descendants)}, polyhierarchy copies={extra_n})"
    )
    return list_obj


def main():
    schemes = list(Concept.objects.filter(nodetype="ConceptScheme"))
    print(f"Found {len(schemes)} concept schemes; existing lists={List.objects.count()}")
    for scheme in schemes:
        convert_scheme(scheme)
    print("DONE")
    for lst in List.objects.all().order_by("name"):
        roots = lst.list_items.filter(parent__isnull=True).count()
        print(f"  {lst.name}: items={lst.list_items.count()} roots={roots}")


if __name__ == "__main__":
    main()
    sys.exit(0)
