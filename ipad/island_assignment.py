"""Assign Indonesian island labels from locality text and WGS84 coordinates.

Uses the existing ``Island - Indonesia`` controlled list (Geography
``Island / Pulau`` widget). Extra list items are added to that same list when
a site sits on an island the original five Greater-Sunda/Papua terms do not
cover. Labels are not invented outside this list.
"""

from __future__ import annotations

import re
import uuid
from functools import lru_cache

from arches_controlled_lists.models import List, ListItem, ListItemValue

LIST_NAME = "Island - Indonesia"
LIST_ID = uuid.UUID("19232db6-c00d-4171-bbfa-dd34ada7a6b8")
ISLAND_NODE_ID = "de49ab5e-dfa5-11ef-8d94-3565fe170f74"

# Existing five items plus islands actually represented in IPAD site localities.
ISLAND_LABELS = (
    "Java",
    "Kalimantan",
    "Sulawesi",
    "Sumatra",
    "West Papua",
    "Bali",
    "Nusa Penida",
    "Lombok",
    "Sumbawa",
    "Flores",
    "Alor",
    "Lembata",
    "Rote",
    "Muna",
    "Buton",
    "Talaud",
    "Ternate",
    "Halmahera",
    "Morotai",
    "Gebe",
    "Obi",
    "Seram",
    "Buru",
    "Haruku",
    "Buano",
    "Kei",
    "Aru",
    "Kisar",
    "Wetang",
    "Nias",
    "Natuna",
    "Maluku",
)

# First matching pattern wins. More specific island names before provinces.
_ADDRESS_RULES: tuple[tuple[str, str], ...] = (
    (r"\bnusa penida\b", "Nusa Penida"),
    (r"\bkarakelong\b", "Talaud"),
    (r"\bsalebabu\b", "Talaud"),
    (r"\bkabaruan\b", "Talaud"),
    (r"\bmerampit\b", "Talaud"),
    (r"\btalauds?\b", "Talaud"),
    (r"\bternate\b", "Ternate"),
    (r"\bhalmahera\b", "Halmahera"),
    (r"\bmorotai\b", "Morotai"),
    (r"\bgebe\b", "Gebe"),
    (r"\bobi\b", "Obi"),
    (r"\bharuku\b", "Haruku"),
    (r"\bbuano\b", "Buano"),
    (r"\bseram\b", "Seram"),
    (r"\bburu\b", "Buru"),
    (r"\baru\b", "Aru"),
    (r"\bkei\b", "Kei"),
    (r"\bkaimear\b", "Kei"),
    (r"\bkisar\b", "Kisar"),
    (r"\bwetang\b", "Wetang"),
    (r"\balor\b", "Alor"),
    (r"\blembata\b", "Lembata"),
    (r"\bflores\b", "Flores"),
    (r"\blombok\b", "Lombok"),
    (r"\bsumbawa\b", "Sumbawa"),
    (r"\bdompu\b", "Sumbawa"),
    (r"\brote\b", "Rote"),
    (r"\bbali\b", "Bali"),
    (r"\bmuna\b", "Muna"),
    (r"\bbuton\b", "Buton"),
    (r"\bbau-?bau\b", "Buton"),
    (r"\bnias\b", "Nias"),
    (r"\bnatuna\b", "Natuna"),
    (r"\bmisool\b", "West Papua"),
    (r"\bwaigeo\b", "West Papua"),
    (r"\braja ampat\b", "West Papua"),
    (r"\bfakfak\b", "West Papua"),
    (r"\bkaimana\b", "West Papua"),
    (r"\btriton\b", "West Papua"),
    (r"\bbitsyari\b", "West Papua"),
    (r"\bjayapura\b", "West Papua"),
    (r"\bkeerom\b", "West Papua"),
    (r"\bwest papua\b", "West Papua"),
    (r"\bpapua\b", "West Papua"),
    (r"\bjava sea\b", "Java"),
    (r"\bmadura\b", "Java"),
    (r"\beast java\b", "Java"),
    (r"\bwest java\b", "Java"),
    (r"\bcentral java\b", "Java"),
    (r"\byogyakarta\b", "Java"),
    (r"\bjakarta\b", "Java"),
    (r"\bbanten\b", "Java"),
    (r"\bbondowoso\b", "Java"),
    (r"\bjember\b", "Java"),
    (r"\bpacitan\b", "Java"),
    (r"\bbandung\b", "Java"),
    (r"\bpati\b", "Java"),
    (r"\brembang\b", "Java"),
    (r"\bgunungkidul\b", "Java"),
    (r"\bsuger\b", "Java"),
    (r"\bpunung\b", "Java"),
    (r"\bkudus\b", "Java"),
    (r"\bmadiun\b", "Java"),
    (r"\bngawi\b", "Java"),
    (r"\btuban\b", "Java"),
    (r"\bjava\b", "Java"),
    (r"\beast kalimantan\b", "Kalimantan"),
    (r"\bsouth kalimantan\b", "Kalimantan"),
    (r"\bsangkulirang\b", "Kalimantan"),
    (r"\bmangkalihat\b", "Kalimantan"),
    (r"\bkalimantan\b", "Kalimantan"),
    (r"\bmaros\b", "Sulawesi"),
    (r"\bpangkep\b", "Sulawesi"),
    (r"\benrekang\b", "Sulawesi"),
    (r"\blore[- ]lindu\b", "Sulawesi"),
    (r"\bmamasa\b", "Sulawesi"),
    (r"\bmamuju\b", "Sulawesi"),
    (r"\bkolaka\b", "Sulawesi"),
    (r"\bkonawe\b", "Sulawesi"),
    (r"\btowuti\b", "Sulawesi"),
    (r"\bluwu\b", "Sulawesi"),
    (r"\brampi\b", "Sulawesi"),
    (r"\bkalumpang\b", "Sulawesi"),
    (r"\bpangale\b", "Sulawesi"),
    (r"\bsouth sulawesi\b", "Sulawesi"),
    (r"\bwest sulawesi\b", "Sulawesi"),
    (r"\bcentral sulawesi\b", "Sulawesi"),
    (r"\bsoutheast sulawesi\b", "Sulawesi"),
    (r"\bnorth sulawesi\b", "Sulawesi"),
    (r"\bsulawesi\b", "Sulawesi"),
    (r"\baceh\b", "Sumatra"),
    (r"\bjambi\b", "Sumatra"),
    (r"\blahat\b", "Sumatra"),
    (r"\bpasemah\b", "Sumatra"),
    (r"\boku\b", "Sumatra"),
    (r"\bsarolangun\b", "Sumatra"),
    (r"\bnorth sumatra\b", "Sumatra"),
    (r"\bsouth sumatra\b", "Sumatra"),
    (r"\bsumatra\b", "Sumatra"),
    (r"\bmaluku islands\b", "Maluku"),
    (r"\bnorth maluku\b", "Maluku"),
    (r"\bmaluku\b", "Maluku"),
)

_COMPILED_RULES = tuple(
    (re.compile(pattern, re.IGNORECASE), label) for pattern, label in _ADDRESS_RULES
)

_DUMMY_LONLAT = (2.8, 3.03)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("|", " ").replace("/", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def island_from_address(address: str | None) -> str | None:
    text = normalize_text(address)
    if not text:
        return None
    for pattern, label in _COMPILED_RULES:
        if pattern.search(text):
            return label
    return None


def island_from_coords(lon: float | None, lat: float | None) -> str | None:
    if lon is None or lat is None:
        return None
    if abs(lon - _DUMMY_LONLAT[0]) < 0.05 and abs(lat - _DUMMY_LONLAT[1]) < 0.05:
        return None
    if not (95.0 <= lon <= 141.5 and -11.5 <= lat <= 6.5):
        return None
    if 96.8 <= lon <= 97.9 and 0.4 <= lat <= 1.5:
        return "Nias"
    if 107.5 <= lon <= 109.2 and 3.0 <= lat <= 4.8:
        return "Natuna"
    if 114.4 <= lon <= 115.75 and -8.9 <= lat <= -8.05:
        return "Bali"
    if 115.75 <= lon <= 116.8 and -8.95 <= lat <= -8.15:
        return "Lombok"
    if 116.8 <= lon <= 119.3 and -9.15 <= lat <= -8.0:
        return "Sumbawa"
    if 119.4 <= lon <= 123.15 and -9.1 <= lat <= -8.05:
        return "Flores"
    if 123.2 <= lon <= 123.9 and -8.65 <= lat <= -8.1:
        return "Lembata"
    if 123.9 <= lon <= 125.25 and -8.65 <= lat <= -8.0:
        return "Alor"
    if 122.55 <= lon <= 123.45 and -11.15 <= lat <= -10.35:
        return "Rote"
    if 126.25 <= lon <= 127.25 and 3.55 <= lat <= 4.85:
        return "Talaud"
    if 127.25 <= lon <= 127.5 and 0.7 <= lat <= 0.9:
        return "Ternate"
    if 105.05 <= lon <= 114.7 and -8.85 <= lat <= -5.4:
        return "Java"
    if 95.0 <= lon <= 106.2 and -6.1 <= lat <= 5.8:
        return "Sumatra"
    if 108.8 <= lon <= 119.2 and -4.25 <= lat <= 7.4:
        return "Kalimantan"
    if 118.7 <= lon <= 125.6 and -6.15 <= lat <= 2.0:
        return "Sulawesi"
    if 129.3 <= lon <= 141.1 and -9.0 <= lat <= 1.2:
        return "West Papua"
    if 125.5 <= lon <= 135.0 and -8.5 <= lat <= 2.6:
        return "Maluku"
    return None


def classify_island(
    address: str | None,
    lon: float | None = None,
    lat: float | None = None,
) -> tuple[str | None, str]:
    """Return ``(island_label, method)`` where method is address, coords, or none."""
    label = island_from_address(address)
    if label:
        return label, "address"
    label = island_from_coords(lon, lat)
    if label:
        return label, "coords"
    return None, "none"


def get_island_list() -> List:
    controlled_list = List.objects.filter(pk=LIST_ID).first()
    if controlled_list is None:
        controlled_list = List.objects.filter(name=LIST_NAME).first()
    if controlled_list is None:
        raise RuntimeError(f"Controlled list {LIST_NAME!r} not found")
    return controlled_list


def ensure_island_items() -> dict[str, ListItem]:
    """Create any missing items on the existing Island - Indonesia list."""
    controlled_list = get_island_list()
    existing: dict[str, ListItem] = {}
    for item in ListItem.objects.filter(list=controlled_list).prefetch_related(
        "list_item_values"
    ):
        for value in item.list_item_values.all():
            if value.valuetype_id == "prefLabel" and value.language_id == "en":
                existing[value.value] = item
    next_sort = max((item.sortorder for item in existing.values()), default=-1) + 1
    created: dict[str, ListItem] = {}
    for label in ISLAND_LABELS:
        if label in existing:
            continue
        item = ListItem(list=controlled_list, sortorder=next_sort)
        item.save()
        item.uri = item.generate_uri()
        item.save(update_fields=["uri"])
        ListItemValue.objects.create(
            list_item=item,
            valuetype_id="prefLabel",
            language_id="en",
            value=label,
        )
        existing[label] = item
        created[label] = item
        next_sort += 1
    return existing


@lru_cache(maxsize=1)
def island_items() -> dict[str, ListItem]:
    return ensure_island_items()


def island_tile_value(label: str) -> list[dict]:
    item = island_items().get(label)
    if item is None:
        raise KeyError(f"Island list has no item {label!r}")
    return [item.build_tile_value()]
