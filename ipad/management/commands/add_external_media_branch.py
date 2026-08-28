"""Add the IPAD Place external-media branch (CIDOC E27→P129i→E73→P128i→E84→P1→E42).

Does not modify:
- heritage_place → assessment_summary → assessment_activity → information_resource (P16)
- information_carrier / file-list
- publication
- external_xref
- the stale Information Resource (archeology) graphid on the assessment IR node
"""

from __future__ import annotations

import copy
import uuid

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Max

from arches.app.models.graph import Graph, GraphValidationError
from arches.app.models.models import (
    CardModel,
    CardXNodeXWidget,
    DDataType,
    Node,
)
from arches_controlled_lists.models import List, ListItem, ListItemValue

CRM = "http://www.cidoc-crm.org/cidoc-crm"
E73 = f"{CRM}/E73_Information_Object"
E84 = f"{CRM}/E84_Information_Carrier"
E42 = f"{CRM}/E42_Identifier"
E55 = f"{CRM}/E55_Type"
E62 = f"{CRM}/E62_String"
P129I = f"{CRM}/P129i_is_subject_of"
P129 = f"{CRM}/P129_is_about"
P128I = f"{CRM}/P128i_is_carried_by"
P1 = f"{CRM}/P1_is_identified_by"
P2 = f"{CRM}/P2_has_type"
P3 = f"{CRM}/P3_has_note"

PLACE_SLUG = "ipad_place_site_archeology"
IR_SLUG = "information_resource_model"

EXTERNAL_MEDIA_ALIAS = "external_media"
EXTERNAL_CARRIER_ALIAS = "external_information_carrier"
FILE_ID_ALIAS = "external_carrier_file_id"
STORAGE_ALIAS = "storage_backend"
MIME_ALIAS = "mime_type"
CAPTION_ALIAS = "caption"

STORAGE_LIST_NAME = "IPAD storage backend"
STORAGE_ITEMS = (
    ("google_drive", "google_drive"),
    ("gcs", "gcs"),
    ("iiif", "iiif"),
)

ASSESSMENT_IR_NODE_ID = uuid.UUID("de49ab79-dfa5-11ef-8d94-3565fe170f74")
ASSESSMENT_IR_EDGE_PROPERTY = f"{CRM}/P16_used_specific_object"


def source_graph(slug: str) -> Graph:
    graph = Graph.objects.filter(slug=slug, source_identifier__isnull=True).first()
    if graph is None:
        raise CommandError(f"Graph slug={slug} not found")
    return graph


def assert_ontology(graph: Graph, domain_class: str, prop: str, range_class: str) -> None:
    ontology_classes = graph.ontology.ontologyclasses.get(source=domain_class)
    for item in ontology_classes.target["down"]:
        if item["ontology_property"] == prop and range_class in item["ontology_classes"]:
            return
    raise CommandError(
        f"Ontology does not allow {domain_class} -[{prop}]-> {range_class}"
    )


def find_node(graph: Graph, alias: str) -> Node | None:
    for node in graph.nodes.values():
        if node.alias == alias:
            return node
    return None


def node_card(graph: Graph, node: Node) -> CardModel:
    for card in graph.cards.values():
        if str(card.nodegroup_id) == str(node.nodegroup_id):
            return card
    raise CommandError(f"No card for node {node.alias}")


def add_widget(graph: Graph, node: Node, card: CardModel, extra_config: dict | None = None) -> None:
    if node.datatype == "semantic":
        return
    for widget in graph.widgets.values():
        if str(widget.node_id) == str(node.pk):
            return
    datatype = DDataType.objects.get(pk=node.datatype)
    if not datatype.defaultwidget_id:
        return
    config = copy.deepcopy(datatype.defaultconfig) if datatype.defaultconfig else {}
    if not isinstance(config, dict):
        config = dict(config or {})
    if extra_config:
        config.update(extra_config)
    config.setdefault("label", node.name)
    widget = CardXNodeXWidget(
        node=node,
        card=card,
        widget_id=datatype.defaultwidget_id,
        config=config,
        label=node.name,
        sortorder=node.sortorder or 0,
    )
    graph.widgets[widget.pk] = widget


def configure_node(graph: Graph, node: Node, *, name: str, alias: str, datatype: str, ontologyclass: str, sortorder: int = 0, config: dict | None = None, isrequired: bool = False) -> None:
    node.name = name
    node.alias = alias
    node.hascustomalias = True
    node.datatype = datatype
    node.ontologyclass = ontologyclass
    node.sortorder = sortorder
    node.isrequired = isrequired
    node.description = ""
    if config is not None:
        node.config = config
    graph.create_node_alias(node)


def configure_edge(graph: Graph, node: Node, ontologyproperty: str) -> None:
    for edge in graph.edges.values():
        if str(edge.rangenode_id) == str(node.pk) or edge.rangenode == node:
            edge.ontologyproperty = ontologyproperty
            return
    raise CommandError(f"No edge found for node {node.alias}")


def append_child(graph: Graph, parent: Node, **kwargs) -> Node:
    result = graph.append_node(nodeid=str(parent.nodeid))
    node = result["node"]
    configure_node(graph, node, **kwargs)
    return node


def ensure_storage_list() -> List:
    existing = List.objects.filter(name=STORAGE_LIST_NAME).first()
    if existing:
        return existing
    controlled_list = List.objects.create(name=STORAGE_LIST_NAME, searchable=False)
    for sortorder, (slug, label) in enumerate(STORAGE_ITEMS):
        item = ListItem(list=controlled_list, sortorder=sortorder)
        item.save()
        item.uri = item.generate_uri()
        item.save(update_fields=["uri"])
        ListItemValue.objects.create(
            list_item=item,
            valuetype_id="prefLabel",
            language_id="en",
            value=label,
        )
    return controlled_list


def ensure_relatable(from_root: Node, to_root: Node) -> None:
    current = {node.pk for node in from_root.get_relatable_resources()}
    if to_root.pk not in current:
        from_root.set_relatable_resources(list(current | {to_root.pk}))


def publish_graph(graph: Graph, user: User, notes: str) -> None:
    graph.publish(user=user, notes=notes)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE resource_instances
            SET graphpublicationid = %s
            WHERE graphid = %s
            """,
            [str(graph.publication_id), str(graph.graphid)],
        )


def assert_assessment_untouched() -> None:
    node = Node.objects.get(pk=ASSESSMENT_IR_NODE_ID)
    if node.alias != "information_resource":
        raise CommandError("Assessment information_resource node alias changed")
    from arches.app.models.models import Edge

    edge = Edge.objects.get(rangenode=node)
    if edge.ontologyproperty != ASSESSMENT_IR_EDGE_PROPERTY:
        raise CommandError("Assessment IR edge property changed")
    domain = edge.domainnode
    if domain.alias != "assessment_activity":
        raise CommandError("Assessment IR parent changed")


class Command(BaseCommand):
    help = "Add Place external-media (P129i) and IR external carrier (P128i/P1) nodes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="admin",
            help="User recorded on the new graph publications (default: admin)",
        )

    def handle(self, *args, **options):
        user = User.objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError(f"User {options['username']} not found")

        place = source_graph(PLACE_SLUG)
        ir = source_graph(IR_SLUG)

        if place.get_draft_graph() or ir.get_draft_graph():
            raise CommandError("A draft graph exists; publish or delete it first.")

        assert_ontology(place, place.root.ontologyclass, P129I, E73)
        assert_ontology(ir, ir.root.ontologyclass, P128I, E84)
        assert_ontology(ir, E84, P1, E42)
        assert_ontology(ir, E84, P2, E55)
        assert_ontology(ir, E84, P3, E62)
        assert_assessment_untouched()

        with transaction.atomic():
            storage_list = ensure_storage_list()
            self._ensure_ir_carrier(ir, storage_list)
            ir.save()
            self._ensure_place_media(place, ir)
            place.save()
            ensure_relatable(place.root, ir.root)
            ensure_relatable(ir.root, place.root)

        ir.refresh_from_database()
        place.refresh_from_database()
        ir.validate()
        place.validate()
        assert_assessment_untouched()

        publish_graph(ir, user, "Add external information carrier (Drive file_id)")
        publish_graph(place, user, "Add external media P129i to Information Resource")

        self.stdout.write(self.style.SUCCESS("External media branch installed and published."))
        self._report(place, ir, storage_list)

    def _ensure_ir_carrier(self, ir: Graph, storage_list: List) -> Node:
        existing = find_node(ir, EXTERNAL_CARRIER_ALIAS)
        if existing:
            self.stdout.write("IR external_information_carrier already present")
            return existing

        result = ir.append_node()
        carrier = result["node"]
        card = result["card"]
        nodegroup = result["nodegroup"]
        configure_node(
            ir,
            carrier,
            name="External Information Carrier",
            alias=EXTERNAL_CARRIER_ALIAS,
            datatype="semantic",
            ontologyclass=E84,
        )
        configure_edge(ir, carrier, P128I)
        ir.add_card(card)
        card.name = "External Information Carrier"
        card.sortorder = (CardModel.objects.filter(graph=ir).aggregate(Max("sortorder")).get("sortorder__max") or 0) + 1
        nodegroup.cardinality = "n"
        ir.get_or_create_nodegroup(nodegroup.nodegroupid).cardinality = "n"
        ir.save()
        ir.refresh_from_database()
        carrier = find_node(ir, EXTERNAL_CARRIER_ALIAS)
        if carrier is None:
            raise CommandError("Failed to persist external_information_carrier")

        file_id = append_child(
            ir,
            carrier,
            name="File ID",
            alias=FILE_ID_ALIAS,
            datatype="string",
            ontologyclass=E42,
            sortorder=0,
            isrequired=True,
            config={},
        )
        configure_edge(ir, file_id, P1)

        storage = append_child(
            ir,
            carrier,
            name="Storage Backend",
            alias=STORAGE_ALIAS,
            datatype="reference",
            ontologyclass=E55,
            sortorder=1,
            isrequired=True,
            config={"multiValue": False, "controlledList": str(storage_list.pk)},
        )
        configure_edge(ir, storage, P2)

        mime = append_child(
            ir,
            carrier,
            name="MIME Type",
            alias=MIME_ALIAS,
            datatype="string",
            ontologyclass=E62,
            sortorder=2,
            config={},
        )
        configure_edge(ir, mime, P3)

        caption = append_child(
            ir,
            carrier,
            name="Caption",
            alias=CAPTION_ALIAS,
            datatype="string",
            ontologyclass=E62,
            sortorder=3,
            config={},
        )
        configure_edge(ir, caption, P3)

        carrier_card = node_card(ir, carrier)
        add_widget(
            ir,
            file_id,
            carrier_card,
            {
                "placeholder": {"en": "Google Drive file ID (not a URL)"},
                "i18n_properties": ["placeholder"],
            },
        )
        add_widget(
            ir,
            storage,
            carrier_card,
            {"placeholder": {"en": "Select storage backend"}, "i18n_properties": ["placeholder"]},
        )
        add_widget(
            ir,
            mime,
            carrier_card,
            {
                "placeholder": {"en": "image/jpeg or application/pdf"},
                "i18n_properties": ["placeholder"],
            },
        )
        add_widget(
            ir,
            caption,
            carrier_card,
            {"placeholder": {"en": "Caption"}, "i18n_properties": ["placeholder"]},
        )
        return carrier

    def _ensure_place_media(self, place: Graph, ir: Graph) -> Node:
        existing = find_node(place, EXTERNAL_MEDIA_ALIAS)
        if existing:
            self.stdout.write("Place external_media already present")
            return existing

        result = place.append_node()
        media = result["node"]
        card = result["card"]
        nodegroup = result["nodegroup"]
        ir_name = ir.root.name
        if isinstance(ir_name, dict):
            ir_name = ir_name.get("en") or next(iter(ir_name.values()), "Information Resource Model")
        configure_node(
            place,
            media,
            name="External Media",
            alias=EXTERNAL_MEDIA_ALIAS,
            datatype="resource-instance",
            ontologyclass=E73,
            config={
                "graphs": [
                    {
                        "name": ir_name,
                        "graphid": str(ir.graphid),
                        "ontologyProperty": P129I,
                        "inverseOntologyProperty": P129,
                        "useOntologyRelationship": True,
                    }
                ],
                "graphid": [str(ir.graphid)],
                "searchDsl": "",
                "searchString": "",
            },
        )
        configure_edge(place, media, P129I)
        place.add_card(card)
        card.name = "External Media"
        card.sortorder = (CardModel.objects.filter(graph=place).aggregate(Max("sortorder")).get("sortorder__max") or 0) + 1
        nodegroup.cardinality = "n"
        place.get_or_create_nodegroup(nodegroup.nodegroupid).cardinality = "n"
        add_widget(
            place,
            media,
            card,
            {
                "placeholder": {"en": "Select an Information Resource"},
                "i18n_properties": ["placeholder"],
                "defaultResourceInstance": [],
            },
        )
        return media

    def _report(self, place: Graph, ir: Graph, storage_list: List) -> None:
        self.stdout.write(f"Place graph: {place.graphid}")
        self.stdout.write(f"IR graph: {ir.graphid}")
        self.stdout.write(f"storage_backend list: {storage_list.pk}")
        for alias in (
            EXTERNAL_MEDIA_ALIAS,
            EXTERNAL_CARRIER_ALIAS,
            FILE_ID_ALIAS,
            STORAGE_ALIAS,
            MIME_ALIAS,
            CAPTION_ALIAS,
        ):
            node = find_node(place, alias) or find_node(ir, alias)
            if node:
                self.stdout.write(f"  {alias} {node.pk} {node.datatype} {node.ontologyclass}")
