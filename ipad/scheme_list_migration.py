"""Convert RDM ConceptSchemes to controlled lists (hasTopConcept + narrower).

Official migrate_collections_to_controlled_lists only walks SKOS Collections
via member relations. Imported thesauri are ConceptSchemes with no Collections.
"""

import uuid
from collections import defaultdict, deque

from django.db import transaction
from django.db.models import Q

from arches.app.models.models import Concept, DValueType, Relation, Value
from arches_controlled_lists.models import List, ListItem, ListItemValue

SKIP_SCHEME_NAMES = {"Candidates"}
_MEMBER_MAPS = None


def scheme_label(scheme, preferred_sort_language="en"):
    labels = list(
        Value.objects.filter(concept=scheme, valuetype_id="prefLabel").values_list(
            "language_id", "value"
        )
    )
    by_lang = {lang: val for lang, val in labels}
    for code in (preferred_sort_language, "en-US", "en"):
        if code in by_lang:
            return by_lang[code]
    return labels[0][1] if labels else str(scheme.pk)


def best_preflabel(concept_id, values_by_concept, preferred_sort_language="en"):
    ranked = []
    for v in values_by_concept.get(concept_id, []):
        if v.valuetype_id != "prefLabel":
            continue
        rank = 0 if v.language_id == preferred_sort_language else 1
        ranked.append((rank, (v.value or "").lower(), v.value or ""))
    ranked.sort()
    return ranked[0][2] if ranked else ""


def convert_scheme(
    scheme,
    host,
    preferred_sort_language="en",
    overwrite=False,
    skip_names=None,
):
    skip_names = skip_names if skip_names is not None else SKIP_SCHEME_NAMES
    name = scheme_label(scheme, preferred_sort_language)
    if name in skip_names:
        return ("skipped_staging", name, None)

    existing = List.objects.filter(Q(pk=scheme.pk) | Q(name=name)).first()
    if existing and not overwrite:
        return ("skipped_exists", existing.name, existing)

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
        return ("skipped_empty", name, None)

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
            decorated.append(
                (
                    so is None,
                    so or 0,
                    best_preflabel(
                        cid, values_by_concept, preferred_sort_language
                    ).lower(),
                    cid,
                )
            )
        decorated.sort()
        for i, row in enumerate(decorated):
            sortorder_map[row[3]] = i

    def uri_for(cid, item_id):
        for val in values_by_concept.get(cid, []):
            if val.valuetype_id == "identifier" and val.value:
                return val.value
        return f"{host.rstrip('/')}/{item_id}"

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
        if overwrite:
            List.objects.filter(Q(pk=scheme.pk) | Q(name=name)).delete()
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

    return ("created", name, list_obj)


def convert_collection(
    collection,
    host,
    preferred_sort_language="en",
    overwrite=False,
):
    """Convert an RDM Collection (skos:member tree) to a controlled list."""
    name = scheme_label(collection, preferred_sort_language)
    if name:
        name = name[:127]
    existing = List.objects.filter(pk=collection.pk).first()
    if existing and not overwrite:
        return ("skipped_exists", existing.name, existing)

    global _MEMBER_MAPS
    if _MEMBER_MAPS is None:
        member_children = defaultdict(list)
        member_parents = defaultdict(list)
        for frm, to in Relation.objects.filter(relationtype="member").values_list(
            "conceptfrom_id", "conceptto_id"
        ):
            member_children[frm].append(to)
            member_parents[to].append(frm)
        _MEMBER_MAPS = (member_children, member_parents)
    member_children, member_parents = _MEMBER_MAPS

    tops = list(member_children.get(collection.pk, []))
    if not tops:
        existing_empty = List.objects.filter(pk=collection.pk).first()
        if existing_empty and not overwrite:
            return ("skipped_exists", existing_empty.name, existing_empty)
        list_obj = List(
            id=collection.pk,
            name=name or str(collection.pk),
            dynamic=False,
            searchable=False,
        )
        if overwrite:
            List.objects.filter(pk=collection.pk).delete()
        list_obj.save()
        return ("created", list_obj.name, list_obj)

    descendants = set()
    queue = deque(tops)
    while queue:
        cid = queue.popleft()
        if cid in descendants or cid == collection.pk:
            continue
        descendants.add(cid)
        for child in member_children.get(cid, []):
            if child not in descendants and child != collection.pk:
                queue.append(child)

    values_by_concept = defaultdict(list)
    note_or_label = set(
        DValueType.objects.filter(category__in=["note", "label"]).values_list(
            "valuetype", flat=True
        )
    )
    for val in Value.objects.filter(concept_id__in=descendants):
        values_by_concept[val.concept_id].append(val)

    primary_parent = {}
    extra_parents = defaultdict(list)
    for cid in descendants:
        in_tree_parents = [
            p
            for p in member_parents.get(cid, [])
            if p in descendants or p == collection.pk
        ]
        in_tree_parents = [p for p in in_tree_parents if p != collection.pk]
        if not in_tree_parents:
            primary_parent[cid] = None
        else:
            primary_parent[cid] = in_tree_parents[0]
            extra_parents[cid] = in_tree_parents[1:]

    sibling_groups = defaultdict(list)
    for cid in descendants:
        sibling_groups[primary_parent[cid]].append(cid)

    sortorder_map = {}
    for parent_id, siblings in sibling_groups.items():
        decorated = []
        for cid in siblings:
            decorated.append(
                (
                    0,
                    0,
                    best_preflabel(
                        cid, values_by_concept, preferred_sort_language
                    ).lower(),
                    cid,
                )
            )
        decorated.sort()
        for i, row in enumerate(decorated):
            sortorder_map[row[3]] = i

    def uri_for(cid, item_id):
        for val in values_by_concept.get(cid, []):
            if val.valuetype_id == "identifier" and val.value:
                return val.value
        return f"{host.rstrip('/')}/{item_id}"

    list_obj = List(id=collection.pk, name=name or str(collection.pk), dynamic=False, searchable=False)
    items = {}
    item_values = []
    used_uris_by_parent = defaultdict(set)

    for cid in descendants:
        item_id = uuid.uuid4()
        uri = uri_for(cid, item_id)
        parent_key = primary_parent[cid]
        if uri in used_uris_by_parent[parent_key]:
            uri = f"{uri}#{item_id}"
        used_uris_by_parent[parent_key].add(uri)
        item = ListItem(
            id=item_id,
            uri=uri,
            list=list_obj,
            sortorder=sortorder_map.get(cid, 0),
            parent=None,
            guide=False,
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
        if "prefLabel" not in {
            v.valuetype_id for v in values_by_concept.get(cid, [])
        } and not any(
            liv.list_item is item and liv.valuetype_id == "prefLabel"
            for liv in item_values
        ):
            item_values.append(
                ListItemValue(
                    list_item=item,
                    valuetype_id="prefLabel",
                    language_id=preferred_sort_language,
                    value=str(cid)[:20],
                )
            )

    duplicates = []
    duplicate_values = []
    for cid, parents in extra_parents.items():
        source = items[cid]
        for parent_cid in parents:
            parent_item = items[parent_cid]
            new_item = ListItem(
                id=uuid.uuid4(),
                uri=f"{source.uri}#{uuid.uuid4()}",
                list=list_obj,
                sortorder=0,
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
        if overwrite:
            List.objects.filter(pk=collection.pk).delete()
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

    return ("created", list_obj.name, list_obj)


def collections_matching(names):
    if not names:
        return list(Concept.objects.filter(nodetype="Collection"))
    concept_ids = Value.objects.filter(
        value__in=names,
        valuetype__in=["prefLabel", "identifier"],
        concept__nodetype="Collection",
    ).values_list("concept_id", flat=True)
    return list(Concept.objects.filter(pk__in=concept_ids, nodetype="Collection"))


def schemes_matching(names):
    """Resolve prefLabel/identifier strings to ConceptScheme objects."""
    if not names:
        return list(Concept.objects.filter(nodetype="ConceptScheme"))
    concept_ids = Value.objects.filter(
        value__in=names,
        valuetype__in=["prefLabel", "identifier"],
        concept__nodetype="ConceptScheme",
    ).values_list("concept_id", flat=True)
    return list(Concept.objects.filter(pk__in=concept_ids, nodetype="ConceptScheme"))
