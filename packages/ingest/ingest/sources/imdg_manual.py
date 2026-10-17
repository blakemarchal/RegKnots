"""Sprint D6.36 — IMDG Code 3.2 Dangerous Goods List entries, hand-curated.

The auto-OCR ingest of IMDG Chapter 3.2 (`packages/ingest/ingest/sources/imdg.py`)
captures ~477 UN entries out of the ~3,000 in the Code, with quality
issues for entries that spanned page breaks or had multi-line names.
The chunker correctly rejected garbled entries (e.g. mis-OCR'd UN 3480
appearing as "alpha-MONOCHLORONAPHTHALEN"), but that left common UN
numbers entirely missing — Madden's UN 3480 lithium-battery query was
the motivating example.

This module fills the gap with entries for the highest-traffic UN numbers
(container-ship cargo, tanker cargo, common chemical manufacturing inputs).

2026-10-17 — rebuilt. The original hand-typed rows were wrong on most
entries: stowage categories (UN 2014 and UN 3532 said A, the Code says D;
UN 1167 said B, the Code says E), invented segregation codes (SG7 on the
lithium batteries, SG2/SG3 on the gases), special provisions that don't
apply, and notes that misdefined the stowage categories (C as "under deck
only", E as "on deck only"). Every value below now comes from BAM DGG-Info
(dgg.bam.de, the German Federal Institute for Materials Research and
Testing's dangerous goods database, IMDG Code Amendment 42-24), checked
entry by entry on 2026-10-17, and the code meanings are the Code's own
wording as BAM shows it (7.1.3.2 stowage categories, 7.1.5 stowage codes,
7.2.5.2 segregation groups, 7.2.8 segregation codes, the EmS Guide).
Where BAM splits one list entry into variants (concentration bands,
"contained in" vs "packed with equipment", vapour pressure for IBCs),
the rows say so. Notes only restate the special provisions' own text.
BAM's data is licensed "Datenlizenz Deutschland – Namensnennung 2.0"
(dl-de/by-2-0: commercial use allowed with the source note every row
carries); its terms forbid automated text and data mining of the
dgg.bam.de site without written consent, so data at scale comes from
BAM's free Dangerous Goods Dataservice download, not the website.

To add an entry: look the UN number up in BAM DGG-Info (IMDG view),
append a UnEntry with one DglRow per packing group (or variant), add any
new code to the meaning tables, and run test_imdg_manual.py.

Source code: `imdg` (same as the auto-OCR entries — these are IMDG
content; we just sourced them differently). Section numbers carry a
"(manual)" suffix so they're identifiable in the chunks table without
preventing them from co-existing with the auto-OCR'd IMDG 3.2 entries,
and so ingest/prune.py never removes them.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE       = "imdg"  # Co-exists with auto-OCR IMDG entries under same source
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 1, 1)  # Amendment 42-24, mandatory from 1 January 2026


# ── What the codes mean (the Code's wording, via BAM DGG-Info) ───────────────

# 7.1.3.2: (cargo ships and passenger ships within the passenger limit,
# other passenger ships)
_STOWAGE_CATEGORY: dict[str, tuple[str, str]] = {
    "A": ("on deck or under deck", "on deck or under deck"),
    "B": ("on deck or under deck", "on deck only"),
    "C": ("on deck only", "on deck only"),
    "D": ("on deck only", "prohibited"),
    "E": ("on deck or under deck", "prohibited"),
}

_STOWAGE_CODES: dict[str, str] = {
    "SW1":  "Protected from sources of heat.",
    "SW2":  "Clear of living quarters.",
    "SW3":  "Shall be transported under temperature control.",
    "SW15": "For metal drums, stowage category B.",
    "SW19": ("For batteries transported in accordance with special provision 376 or 377, "
             "stowage category C, unless transported on a short international voyage."),
    "SW29": ("For engines or machinery containing fuels with a flash point of 23 °C or above, "
             "stowage category A."),
}

_SEGREGATION_GROUPS: dict[str, str] = {
    "SGG1": "acids",
    "SGG8": "hypochlorites",
    "SGG16": "peroxides",
    "SGG18": "alkalis",
}

_SEGREGATION_CODES: dict[str, str] = {
    "SG16": 'Stow "separated from" class 4.1.',
    "SG20": 'Stow "away from" SGG1 (acids).',
    "SG22": 'Stow "away from" ammonium salts.',
    "SG35": 'Stow "separated from" SGG1 (acids).',
    "SG36": 'Stow "separated from" SGG18 (alkalis).',
    "SG49": 'Stow "separated from" SGG6 (cyanides).',
    "SG59": 'Stow "separated from" SGG14 (permanganates).',
    "SG72": "See the tables in 7.2.6.3.",
}

_EMS: dict[str, str] = {
    "F-A": "Fire Schedule A (Alfa), general fire schedule",
    "F-C": "Fire Schedule C (Charlie), non-flammable gases",
    "F-D": "Fire Schedule D (Delta), flammable gases",
    "F-E": "Fire Schedule E (Echo), non-water-reactive flammable liquids",
    "F-F": "Fire Schedule F (Foxtrot), temperature-controlled self-reactive substances and organic peroxides",
    "F-H": "Fire Schedule H (Hotel), oxidizing substances with explosive potential",
    "F-J": "Fire Schedule J (Juliet), non-temperature-controlled self-reactive substances and organic peroxides",
    "S-A": "Spillage Schedule A (Alfa), toxic substances",
    "S-B": "Spillage Schedule B (Bravo), corrosive substances",
    "S-D": "Spillage Schedule D (Delta), flammable liquids",
    "S-E": "Spillage Schedule E (Echo), flammable liquids floating on water",
    "S-G": "Spillage Schedule G (Golf), flammable solids and self-reactive substances",
    "S-I": "Spillage Schedule I (India), flammable solids (repacking possible)",
    "S-K": "Spillage Schedule K (Kilo), temperature-controlled self-reactive substances",
    "S-Q": "Spillage Schedule Q (Quebec), oxidizing substances",
    "S-U": "Spillage Schedule U (Uniform), gases (flammable, toxic or corrosive)",
    "S-V": "Spillage Schedule V (Victor), gases (non-flammable, non-toxic)",
}

# 7.1.3.2's first column covers passenger ships within the passenger limit too.
_CARGO_SHIPS = "Cargo ships includes passenger ships with up to 25 passengers, or 1 per 3 m of length if more."

# The source note BAM's licence asks for (provider, licence, dataset; marked as edited).
_ATTRIBUTION = ("Source: Bundesanstalt für Materialforschung und -prüfung (BAM) – Datenbank GEFAHRGUT – "
                "https://tes.bam.de/en/dangerous-goods-database, dl-de/by-2-0; reformatted.")

# An EmS written with "!" is a special case (underlined in the Code).
_SPECIAL_CASE = "special case: the EmS Guide gives additional advice for this entry"

# Fixed field order, with the label used on its own line ("Packagings: P001")
# and inside a packing-group line ("packagings P001").
_FIELDS: tuple[tuple[str, str], ...] = (
    ("special_provisions", "Special provisions"),
    ("limited_quantity", "Limited quantity"),
    ("excepted_quantity", "Excepted quantity"),
    ("packagings", "Packagings"),
    ("ibc", "IBCs"),
    ("large_packagings", "Large packagings"),
    ("portable_tanks", "Portable tanks"),
    ("stowage_category", "Stowage category"),
    ("stowage_codes", "Stowage and handling"),
    ("segregation_group", "Segregation group"),
    ("segregation_codes", "Segregation codes (besides the class table, 7.2.4)"),
)


def _codes(value: str) -> list[str]:
    return [c.strip() for c in value.split(",") if c.strip()]


@dataclass(frozen=True)
class DglRow:
    """One row of the Dangerous Goods List: a packing group, or a variant BAM
    lists separately. Empty strings mean "none" / "not permitted"."""

    packing_group:      str | None    # "I" / "II" / "III", None for gases and articles
    special_provisions: str           # "274, 386"
    limited_quantity:   str           # "1 L", "100 mL"; "0" = not permitted as a limited quantity
    excepted_quantity:  str           # "E2"; "E0" = not permitted as an excepted quantity
    packagings:         str           # "P504 (PP10)"
    ibc:                str           # "IBC02 (B5)"
    large_packagings:   str           # "LP01"
    portable_tanks:     str           # "T7 (TP2, TP6, TP24)"
    stowage_category:   str           # "A".."E" (7.1.3.2)
    stowage_codes:      str = ""      # "SW1, SW2" (column 16a)
    segregation_group:  str = ""      # "SGG16" (7.2.5.2)
    segregation_codes:  str = ""      # "SG16, SG59" (column 16b)
    variant:            str = ""      # what this row covers when it isn't just the packing group

    def value(self, field: str) -> str:
        raw = getattr(self, field)
        if field == "special_provisions":
            return raw or "none"
        if field == "limited_quantity":
            return "0 (not permitted as a limited quantity)" if raw == "0" else raw
        if field == "excepted_quantity":
            return f"{raw} (not permitted as an excepted quantity)" if raw == "E0" else raw
        if field in ("ibc", "large_packagings", "portable_tanks"):
            return raw or "not permitted"
        if field == "segregation_group":
            return f"{raw} ({_SEGREGATION_GROUPS[raw]})" if raw else "none"
        return raw or "none"

    @property
    def label(self) -> str:
        if self.packing_group:
            pg = f"Packing group {self.packing_group}"
            return f"{pg} ({self.variant})" if self.variant else pg
        return self.variant[:1].upper() + self.variant[1:] if self.variant else "No packing group"


@dataclass(frozen=True)
class UnEntry:
    """One UN number of the IMDG Chapter 3.2 Dangerous Goods List."""

    un_number:            int
    proper_shipping_name: str
    class_:               str
    ems:                  str                 # "F-E, S-E!"; "!" marks a special case
    rows:                 tuple[DglRow, ...]
    subsidiary_hazard:    str = ""
    marine_pollutant:     bool = False        # "P" in column 4 of the list
    notes:                str = ""            # special provisions' own text, shortened

    @property
    def section_number(self) -> str:
        return f"IMDG 3.2 UN {self.un_number} (manual)"

    @property
    def section_title(self) -> str:
        return f"UN {self.un_number} — {self.proper_shipping_name}"

    def render(self) -> str:
        """Format the entry as the chunk full_text."""
        cls = f"{self.class_}; subsidiary hazard {self.subsidiary_hazard}" if self.subsidiary_hazard else self.class_
        mp = "yes" if self.marine_pollutant else "not marked (see chapter 2.10)"
        ems = ", ".join(
            f"{code.rstrip('!')} ({_SPECIAL_CASE})" if code.endswith("!") else code
            for code in _codes(self.ems)
        )
        lines = [
            "[IMDG 3.2 — Dangerous Goods List, Amendment 42-24]",
            _ATTRIBUTION,
            f"Class: {cls}",
            f"Marine pollutant mark (P): {mp}",
            f"EmS: {ems}",
        ]

        rows = self.rows
        fields = [(f, label) for f, label in _FIELDS
                  if f != "segregation_group" or any(r.segregation_group for r in rows)]
        if len(rows) == 1:
            row = rows[0]
            lines.append(f"Packing group: {row.packing_group or 'none'}"
                         + (f" ({row.variant})" if row.variant else ""))
            lines += [f"{label}: {row.value(f)}" for f, label in fields]
        else:
            same = [(f, label) for f, label in fields
                    if len({r.value(f) for r in rows}) == 1]
            differ = [(f, label) for f, label in fields if (f, label) not in same]
            lines += [f"{label}: {rows[0].value(f)}" for f, label in same]
            for row in rows:
                parts = "; ".join(f"{_inline(label)} {row.value(f)}" for f, label in differ)
                lines.append(f"{row.label}: {parts}")

        lines.append("What the codes mean:")
        for cat in sorted({r.stowage_category for r in rows}):
            cargo, passenger = _STOWAGE_CATEGORY[cat]
            lines.append(f"- Stowage category {cat}: cargo ships {cargo}; other passenger ships {passenger}.")
        lines.append(f"  ({_CARGO_SHIPS})")
        for code in sorted({c for r in rows for c in _codes(r.stowage_codes)}, key=_natural):
            lines.append(f"- {code}: {_STOWAGE_CODES[code]}")
        for code in sorted({c for r in rows for c in _codes(r.segregation_codes)}, key=_natural):
            lines.append(f"- {code}: {_SEGREGATION_CODES[code]}")
        for code in _codes(self.ems):
            lines.append(f"- {code.rstrip('!')}: {_EMS[code.rstrip('!')]}.")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines) + "\n"


def _inline(label: str) -> str:
    return label if label.isupper() or label.startswith("IBC") else label.lower()


def _natural(code: str) -> tuple[str, int]:
    head = code.rstrip("0123456789")
    return head, int(code[len(head):] or 0)


# ── Shared row shapes ────────────────────────────────────────────────────────

_IBC_VAPOUR = "IBC02 (none above 110 kPa vapour pressure at 50 °C)"
_PG_I_CLASS3 = "initial boiling point ≤ 35 °C"
_PG_II_CLASS3 = "flash point < 23 °C, initial boiling point > 35 °C"
_PG_III_CLASS3 = "flash point 23–60 °C"

_LITHIUM_IN_EQUIPMENT = dict(
    limited_quantity="0", excepted_quantity="E0", ibc="", portable_tanks="",
    stowage_category="A", stowage_codes="SW19",
)

_POLYMERIZING_NOTE = (
    "SP 386: when stabilized by temperature control, 7.3.7 applies; when chemically stabilized, "
    "the consignor ensures the stabilization prevents dangerous polymerization at a bulk mean "
    "temperature of 50 °C (45 °C in a portable tank), and temperature control is required where "
    "chemical stabilization would become ineffective during the journey. SP 274: the technical "
    "name is added to the proper shipping name in documents and package marking."
)

_FUEL_GAS_NOTE = (
    "SP 392: fuel gas containment systems designed for motor vehicles may be carried for "
    "disposal, recycling, repair, inspection or maintenance, or from manufacture to a vehicle "
    "assembly plant, under the conditions of SP 392."
)


# ── Curated UN entries (BAM DGG-Info, IMDG Code Amendment 42-24, 2026-10-17) ──
#
# Coverage rationale: prioritized by 2026 container-ship + tanker cargo
# frequency. Lithium batteries (3480/3481) are the #1 most-asked Class 9
# question. Common bulk-liquid-tanker cargoes (1267 crude, 1170 ethanol,
# 1830 sulphuric, 1789 HCl) anchor Class 3 and Class 8 coverage.
# Polymerizing substances (3531-3534) added because Madden's session
# specifically queried UN 3532 stowage for divinylbenzene.

UN_ENTRIES: list[UnEntry] = [
    # ── Class 9 — lithium batteries ─────────────────────────────────────────
    UnEntry(
        un_number=3480,
        proper_shipping_name="LITHIUM ION BATTERIES (including lithium ion polymer batteries)",
        class_="9", ems="F-A, S-I",
        rows=(DglRow(
            packing_group=None, special_provisions="188, 230, 310, 348, 376, 377, 384, 387",
            packagings="P903, P908, P909, P910, P911",
            large_packagings="LP903, LP904, LP905, LP906", **_LITHIUM_IN_EQUIPMENT,
        ),),
        notes=(
            "SP 188: lithium-ion cells of not more than 20 Wh and batteries of not more than "
            "100 Wh are not subject to the other provisions of the Code when SP 188's packing, "
            "marking and test conditions are met. SP 376: damaged or defective cells and "
            "batteries. SP 377: cells and batteries carried for disposal or recycling (packing "
            "instruction P909). SP 384: label Model No. 9A; cargo transport units are placarded "
            "with Model No. 9. SP 348: batteries made after 31 December 2011 are marked with "
            "the watt-hour rating on the outside case."
        ),
    ),
    UnEntry(
        un_number=3481,
        proper_shipping_name=(
            "LITHIUM ION BATTERIES CONTAINED IN EQUIPMENT (including lithium ion polymer batteries) "
            "or LITHIUM ION BATTERIES PACKED WITH EQUIPMENT (including lithium ion polymer batteries)"
        ),
        class_="9", ems="F-A, S-I",
        rows=(
            DglRow(packing_group=None, variant="contained in equipment",
                   special_provisions="188, 230, 310, 348, 360, 376, 377, 384, 387, 390",
                   packagings="P903, P908, P909, P910, P911",
                   large_packagings="LP903, LP904, LP905, LP906", **_LITHIUM_IN_EQUIPMENT),
            DglRow(packing_group=None, variant="packed with equipment",
                   special_provisions="188, 230, 310, 348, 360, 376, 377, 384, 387, 390",
                   packagings="P903, P910", large_packagings="", **_LITHIUM_IN_EQUIPMENT),
        ),
        notes=(
            "SP 188 limits as for UN 3480 (20 Wh per cell, 100 Wh per battery). SP 360: vehicles "
            "powered only by lithium or sodium ion batteries go under UN 3556, 3557 or 3558 "
            "instead. SP 390: marking and documentation when one package holds batteries both "
            "contained in and packed with equipment."
        ),
    ),
    UnEntry(
        un_number=3090,
        proper_shipping_name="LITHIUM METAL BATTERIES (including lithium alloy batteries)",
        class_="9", ems="F-A, S-I",
        rows=(DglRow(
            packing_group=None, special_provisions="188, 230, 310, 376, 377, 384, 387",
            packagings="P903, P908, P909, P910, P911",
            large_packagings="LP903, LP904, LP905, LP906", **_LITHIUM_IN_EQUIPMENT,
        ),),
        notes=(
            "SP 188: lithium metal cells with not more than 1 g of lithium and batteries with not "
            "more than 2 g in aggregate are not subject to the other provisions of the Code when "
            "SP 188's packing, marking and test conditions are met. SP 376: damaged or defective "
            "cells and batteries. SP 377: carried for disposal or recycling (P909). SP 387: "
            "batteries containing both lithium metal and lithium ion cells go under UN 3090 or "
            "3091. SP 384: label Model No. 9A."
        ),
    ),
    UnEntry(
        un_number=3091,
        proper_shipping_name=(
            "LITHIUM METAL BATTERIES CONTAINED IN EQUIPMENT (including lithium alloy batteries) "
            "or LITHIUM METAL BATTERIES PACKED WITH EQUIPMENT (including lithium alloy batteries)"
        ),
        class_="9", ems="F-A, S-I",
        rows=(
            DglRow(packing_group=None, variant="contained in equipment",
                   special_provisions="188, 230, 310, 360, 376, 377, 384, 387, 390",
                   packagings="P903, P908, P909, P910, P911",
                   large_packagings="LP903, LP904, LP905, LP906", **_LITHIUM_IN_EQUIPMENT),
            DglRow(packing_group=None, variant="packed with equipment",
                   special_provisions="188, 230, 310, 360, 376, 377, 384, 387, 390",
                   packagings="P903, P910", large_packagings="", **_LITHIUM_IN_EQUIPMENT),
        ),
        notes=(
            "SP 188 limits as for UN 3090 (1 g of lithium per cell, 2 g per battery). SP 360: "
            "vehicles powered only by lithium batteries go under UN 3556, 3557 or 3558 instead. "
            "SP 390: marking and documentation when one package holds batteries both contained "
            "in and packed with equipment."
        ),
    ),

    # ── Class 4.1 — polymerizing substances (Madden's query) ────────────────
    UnEntry(
        un_number=3532,
        proper_shipping_name="POLYMERIZING SUBSTANCE, LIQUID, STABILIZED, N.O.S.",
        class_="4.1", ems="F-J, S-G",
        rows=(DglRow(
            packing_group="III", special_provisions="274, 386", limited_quantity="0",
            excepted_quantity="E0", packagings="P001 (PP93)", ibc="IBC03 (B19)",
            large_packagings="", portable_tanks="T7 (TP4, TP6)", stowage_category="D",
            stowage_codes="SW1", segregation_codes="SG35, SG36",
        ),),
        notes=(
            "BAM classifies technical divinylbenzene (isomer mixtures up to 85%, stabilized) "
            "under this entry. " + _POLYMERIZING_NOTE
        ),
    ),
    UnEntry(
        un_number=3534,
        proper_shipping_name="POLYMERIZING SUBSTANCE, LIQUID, TEMPERATURE CONTROLLED, N.O.S.",
        class_="4.1", ems="F-F, S-K",
        rows=(DglRow(
            packing_group="III", special_provisions="274, 386", limited_quantity="0",
            excepted_quantity="E0", packagings="P001 (PP93)", ibc="IBC03 (B19)",
            large_packagings="", portable_tanks="T7 (TP4, TP6)", stowage_category="D",
            stowage_codes="SW1, SW3", segregation_codes="SG35, SG36",
        ),),
        notes=_POLYMERIZING_NOTE,
    ),
    UnEntry(
        un_number=3531,
        proper_shipping_name="POLYMERIZING SUBSTANCE, SOLID, STABILIZED, N.O.S.",
        class_="4.1", ems="F-J, S-G",
        rows=(DglRow(
            packing_group="III", special_provisions="274, 386", limited_quantity="0",
            excepted_quantity="E0", packagings="P002 (PP92)", ibc="IBC07 (B18)",
            large_packagings="", portable_tanks="T7 (TP4, TP6, TP33)", stowage_category="D",
            stowage_codes="SW1", segregation_codes="SG35, SG36",
        ),),
        notes=_POLYMERIZING_NOTE,
    ),
    UnEntry(
        un_number=3533,
        proper_shipping_name="POLYMERIZING SUBSTANCE, SOLID, TEMPERATURE CONTROLLED, N.O.S.",
        class_="4.1", ems="F-F, S-K",
        rows=(DglRow(
            packing_group="III", special_provisions="274, 386", limited_quantity="0",
            excepted_quantity="E0", packagings="P002 (PP92)", ibc="IBC07 (B18)",
            large_packagings="", portable_tanks="T7 (TP4, TP6, TP33)", stowage_category="D",
            stowage_codes="SW1, SW3", segregation_codes="SG35, SG36",
        ),),
        notes=_POLYMERIZING_NOTE,
    ),

    # ── Class 3 — flammable liquids ─────────────────────────────────────────
    UnEntry(
        un_number=1267,
        proper_shipping_name="PETROLEUM CRUDE OIL",
        class_="3", ems="F-E, S-E",
        rows=(
            DglRow(packing_group="I", variant=_PG_I_CLASS3, special_provisions="357",
                   limited_quantity="500 mL", excepted_quantity="E3", packagings="P001",
                   ibc="", large_packagings="", portable_tanks="T11 (TP1, TP8)",
                   stowage_category="E"),
            DglRow(packing_group="II", variant=_PG_II_CLASS3, special_provisions="357",
                   limited_quantity="1 L", excepted_quantity="E2", packagings="P001",
                   ibc=_IBC_VAPOUR, large_packagings="", portable_tanks="T4 (TP1, TP8)",
                   stowage_category="B"),
            DglRow(packing_group="III", variant=_PG_III_CLASS3, special_provisions="223, 357",
                   limited_quantity="5 L", excepted_quantity="E1", packagings="P001",
                   ibc="IBC03", large_packagings="LP01", portable_tanks="T2 (TP1)",
                   stowage_category="A"),
        ),
        notes=(
            "SP 357: crude oil containing enough hydrogen sulphide that its vapours can present "
            "an inhalation hazard is consigned as UN 3494 PETROLEUM SOUR CRUDE OIL, FLAMMABLE, "
            "TOXIC."
        ),
    ),
    UnEntry(
        un_number=1170,
        proper_shipping_name="ETHANOL (ETHYL ALCOHOL) or ETHANOL SOLUTION (ETHYL ALCOHOL SOLUTION)",
        class_="3", ems="F-E, S-D",
        rows=(
            DglRow(packing_group="II",
                   variant="ethanol, and aqueous solutions with more than 58% ethanol by volume",
                   special_provisions="144", limited_quantity="1 L", excepted_quantity="E2",
                   packagings="P001", ibc="IBC02", large_packagings="",
                   portable_tanks="T4 (TP1)", stowage_category="A"),
            DglRow(packing_group="III",
                   variant="aqueous solutions with more than 24% and not more than 58% ethanol by volume",
                   special_provisions="144, 223", limited_quantity="5 L", excepted_quantity="E1",
                   packagings="P001", ibc="IBC03", large_packagings="LP01",
                   portable_tanks="T2 (TP1)", stowage_category="A"),
        ),
        notes=(
            "SP 144: an aqueous solution containing not more than 24% alcohol by volume is not "
            "subject to the Code. The concentration bands are BAM's; the packing group follows "
            "the class 3 flash point criteria (chapter 2.3)."
        ),
    ),
    UnEntry(
        un_number=1202,
        proper_shipping_name="GAS OIL or DIESEL FUEL or HEATING OIL, LIGHT",
        class_="3", ems="F-E, S-E",
        rows=(DglRow(
            packing_group="III", special_provisions="", limited_quantity="5 L",
            excepted_quantity="E1", packagings="P001", ibc="IBC03", large_packagings="LP01",
            portable_tanks="T2 (TP1)", stowage_category="A",
        ),),
        notes=(
            "Two list entries share UN 1202: flash point not more than 60 °C, and fuel complying "
            "with standard EN 590:2013 + A1:2017. Both carry the values above."
        ),
    ),
    UnEntry(
        un_number=1203,
        proper_shipping_name="MOTOR SPIRIT or GASOLINE or PETROL",
        class_="3", ems="F-E, S-E",
        rows=(DglRow(
            packing_group="II", special_provisions="243", limited_quantity="1 L",
            excepted_quantity="E2", packagings="P001", ibc="IBC02", large_packagings="",
            portable_tanks="T4 (TP1)", stowage_category="E",
        ),),
        notes=(
            "SP 243: gasoline, motor spirit and petrol for spark-ignition engines are assigned to "
            "this entry regardless of variations in volatility."
        ),
    ),
    UnEntry(
        un_number=1219,
        proper_shipping_name="ISOPROPANOL (ISOPROPYL ALCOHOL)",
        class_="3", ems="F-E, S-D",
        rows=(DglRow(
            packing_group="II", special_provisions="", limited_quantity="1 L",
            excepted_quantity="E2", packagings="P001", ibc="IBC02", large_packagings="",
            portable_tanks="T4 (TP1)", stowage_category="B",
        ),),
    ),
    UnEntry(
        un_number=1993,
        proper_shipping_name="FLAMMABLE LIQUID, N.O.S.",
        class_="3", ems="F-E, S-E!",
        rows=(
            DglRow(packing_group="I", variant=_PG_I_CLASS3, special_provisions="274",
                   limited_quantity="0", excepted_quantity="E3", packagings="P001", ibc="",
                   large_packagings="", portable_tanks="T11 (TP1, TP27)", stowage_category="E"),
            DglRow(packing_group="II", variant=_PG_II_CLASS3, special_provisions="274",
                   limited_quantity="1 L", excepted_quantity="E2", packagings="P001",
                   ibc=_IBC_VAPOUR, large_packagings="",
                   portable_tanks="T7 (TP1, TP8, TP28)", stowage_category="B"),
            DglRow(packing_group="III", variant=_PG_III_CLASS3, special_provisions="223, 274, 955",
                   limited_quantity="5 L", excepted_quantity="E1", packagings="P001",
                   ibc="IBC03", large_packagings="LP01", portable_tanks="T4 (TP1, TP29)",
                   stowage_category="A"),
        ),
        notes=(
            "SP 274: the technical name is added to the proper shipping name in documents and "
            "package marking."
        ),
    ),
    UnEntry(
        un_number=1167,
        proper_shipping_name="DIVINYL ETHER, STABILIZED",
        class_="3", ems="F-E, S-D",
        rows=(DglRow(
            packing_group="I", special_provisions="386", limited_quantity="0",
            excepted_quantity="E3", packagings="P001", ibc="", large_packagings="",
            portable_tanks="T11 (TP2)", stowage_category="E", stowage_codes="SW1, SW2",
        ),),
        notes=(
            "Divinyl ether is not divinylbenzene: BAM classifies technical divinylbenzene "
            "(isomer mixtures up to 85%, stabilized) as UN 3532. SP 386: chemical stabilization "
            "must prevent dangerous polymerization at a bulk mean temperature of 50 °C (45 °C in "
            "a portable tank); otherwise temperature control applies (7.3.7)."
        ),
    ),

    # ── Class 8 — corrosives ────────────────────────────────────────────────
    UnEntry(
        un_number=1789,
        proper_shipping_name="HYDROCHLORIC ACID",
        class_="8", ems="F-A, S-B",
        rows=(
            DglRow(packing_group="II", special_provisions="", limited_quantity="1 L",
                   excepted_quantity="E2", packagings="P001", ibc="IBC02 (B20)",
                   large_packagings="", portable_tanks="T8 (TP2)", stowage_category="C",
                   segregation_group="SGG1", segregation_codes="SG36, SG49"),
            DglRow(packing_group="III", special_provisions="223", limited_quantity="5 L",
                   excepted_quantity="E1", packagings="P001", ibc="IBC03",
                   large_packagings="LP01", portable_tanks="T4 (TP1)", stowage_category="C",
                   segregation_group="SGG1", segregation_codes="SG36, SG49"),
        ),
    ),
    UnEntry(
        un_number=1830,
        proper_shipping_name="SULPHURIC ACID with more than 51% acid",
        class_="8", ems="F-A, S-B",
        rows=(DglRow(
            packing_group="II", special_provisions="", limited_quantity="1 L",
            excepted_quantity="E2", packagings="P001", ibc="IBC02 (B20)", large_packagings="",
            portable_tanks="T8 (TP2)", stowage_category="C", stowage_codes="SW15",
            segregation_group="SGG1", segregation_codes="SG36, SG49",
        ),),
    ),
    UnEntry(
        un_number=1719,
        proper_shipping_name="CAUSTIC ALKALI LIQUID, N.O.S.",
        class_="8", ems="F-A, S-B",
        rows=(
            DglRow(packing_group="II", special_provisions="274", limited_quantity="1 L",
                   excepted_quantity="E2", packagings="P001", ibc="IBC02",
                   large_packagings="", portable_tanks="T11 (TP2, TP27)", stowage_category="A",
                   segregation_group="SGG18", segregation_codes="SG22, SG35"),
            DglRow(packing_group="III", special_provisions="223, 274", limited_quantity="5 L",
                   excepted_quantity="E1", packagings="P001", ibc="IBC03",
                   large_packagings="", portable_tanks="T7 (TP1, TP28)", stowage_category="A",
                   segregation_group="SGG18", segregation_codes="SG22, SG35"),
        ),
        notes=(
            "SP 274: the technical name is added to the proper shipping name in documents and "
            "package marking."
        ),
    ),
    UnEntry(
        un_number=1824,
        proper_shipping_name="SODIUM HYDROXIDE SOLUTION",
        class_="8", ems="F-A, S-B",
        rows=(
            DglRow(packing_group="II", special_provisions="", limited_quantity="1 L",
                   excepted_quantity="E2", packagings="P001", ibc="IBC02",
                   large_packagings="", portable_tanks="T7 (TP2)", stowage_category="A",
                   segregation_group="SGG18", segregation_codes="SG35"),
            DglRow(packing_group="III", special_provisions="223", limited_quantity="5 L",
                   excepted_quantity="E1", packagings="P001", ibc="IBC03",
                   large_packagings="LP01", portable_tanks="T4 (TP1)", stowage_category="A",
                   segregation_group="SGG18", segregation_codes="SG35"),
        ),
    ),
    UnEntry(
        un_number=1791,
        proper_shipping_name="HYPOCHLORITE SOLUTION",
        class_="8", ems="F-A, S-B!", marine_pollutant=True,
        rows=(
            DglRow(packing_group="II", special_provisions="274, 900", limited_quantity="1 L",
                   excepted_quantity="E2", packagings="P001 (PP10)", ibc="IBC02 (B5)",
                   large_packagings="", portable_tanks="T7 (TP2, TP24)", stowage_category="B",
                   segregation_group="SGG8", segregation_codes="SG20"),
            DglRow(packing_group="III", special_provisions="223, 274, 900", limited_quantity="5 L",
                   excepted_quantity="E1", packagings="P001", ibc="IBC03",
                   large_packagings="LP01", portable_tanks="T4 (TP2, TP24)", stowage_category="B",
                   segregation_group="SGG8", segregation_codes="SG20"),
        ),
        notes=(
            "SP 900: ammonium hypochlorite is prohibited from transport. PP10 and B5: packagings "
            "(packing group II) are vented and IBCs carry a venting device. SP 274: the technical "
            "name is added to the proper shipping name."
        ),
    ),

    # ── Class 6.1 — toxic substances ────────────────────────────────────────
    UnEntry(
        un_number=2810,
        proper_shipping_name="TOXIC LIQUID, ORGANIC, N.O.S.",
        class_="6.1", ems="F-A, S-A",
        rows=(
            DglRow(packing_group="I", special_provisions="274, 315", limited_quantity="0",
                   excepted_quantity="E5", packagings="P001", ibc="", large_packagings="",
                   portable_tanks="T14 (TP2, TP13, TP27)", stowage_category="B",
                   stowage_codes="SW2"),
            DglRow(packing_group="II", special_provisions="274", limited_quantity="100 mL",
                   excepted_quantity="E4", packagings="P001", ibc="IBC02", large_packagings="",
                   portable_tanks="T11 (TP2, TP13, TP27)", stowage_category="B",
                   stowage_codes="SW2"),
            DglRow(packing_group="III", special_provisions="223, 274", limited_quantity="5 L",
                   excepted_quantity="E1", packagings="P001", ibc="IBC03",
                   large_packagings="LP01", portable_tanks="T7 (TP1, TP28)",
                   stowage_category="A", stowage_codes="SW2"),
        ),
        notes=(
            "SP 274: the technical name is added to the proper shipping name. SP 315: not for "
            "class 6.1 substances that meet the packing group I inhalation toxicity criteria "
            "(2.6.2.2.4.3)."
        ),
    ),
    UnEntry(
        un_number=1547,
        proper_shipping_name="ANILINE",
        class_="6.1", ems="F-A, S-A!", marine_pollutant=True,
        rows=(DglRow(
            packing_group="II", special_provisions="279", limited_quantity="100 mL",
            excepted_quantity="E4", packagings="P001", ibc="IBC02", large_packagings="",
            portable_tanks="T7 (TP2)", stowage_category="A", stowage_codes="SW2",
            segregation_codes="SG35",
        ),),
        notes="SP 279: assigned to this class and packing group on human experience.",
    ),

    # ── Class 2 — gases ─────────────────────────────────────────────────────
    UnEntry(
        un_number=1075,
        proper_shipping_name="PETROLEUM GASES, LIQUEFIED",
        class_="2.1", ems="F-D!, S-U",
        rows=(DglRow(
            packing_group=None, special_provisions="392", limited_quantity="0",
            excepted_quantity="E0", packagings="P200", ibc="", large_packagings="",
            portable_tanks="T50", stowage_category="E", stowage_codes="SW2",
        ),),
        notes=_FUEL_GAS_NOTE,
    ),
    UnEntry(
        un_number=1972,
        proper_shipping_name=(
            "METHANE, REFRIGERATED LIQUID or NATURAL GAS, REFRIGERATED LIQUID with high methane content"
        ),
        class_="2.1", ems="F-D!, S-U",
        rows=(DglRow(
            packing_group=None, special_provisions="", limited_quantity="0",
            excepted_quantity="E0", packagings="P203", ibc="", large_packagings="",
            portable_tanks="T75 (TP5)", stowage_category="D", stowage_codes="SW2",
        ),),
        notes="LNG carried in bulk on gas carriers is governed by the IGC Code, not this list.",
    ),
    UnEntry(
        un_number=1066,
        proper_shipping_name="NITROGEN, COMPRESSED",
        class_="2.2", ems="F-C, S-V",
        rows=(DglRow(
            packing_group=None, special_provisions="378, 392, 406", limited_quantity="120 mL",
            excepted_quantity="E1", packagings="P200", ibc="", large_packagings="",
            portable_tanks="", stowage_category="A",
        ),),
        notes=(
            "SP 406: may be carried as a limited quantity in pressure receptacles of not more "
            "than 1,000 mL meeting P200, under SP 406's conditions. SP 378: radiation detectors "
            "containing this gas, under conditions. " + _FUEL_GAS_NOTE
        ),
    ),
    UnEntry(
        un_number=1978,
        proper_shipping_name="PROPANE",
        class_="2.1", ems="F-D, S-U",
        rows=(DglRow(
            packing_group=None, special_provisions="392", limited_quantity="0",
            excepted_quantity="E0", packagings="P200", ibc="", large_packagings="",
            portable_tanks="T50", stowage_category="E", stowage_codes="SW2",
        ),),
        notes=_FUEL_GAS_NOTE,
    ),
    UnEntry(
        un_number=1011,
        proper_shipping_name="BUTANE",
        class_="2.1", ems="F-D, S-U",
        rows=(DglRow(
            packing_group=None, special_provisions="392", limited_quantity="0",
            excepted_quantity="E0", packagings="P200", ibc="", large_packagings="",
            portable_tanks="T50", stowage_category="E", stowage_codes="SW2",
        ),),
        notes=_FUEL_GAS_NOTE,
    ),

    # ── Class 5.1 — oxidizers ───────────────────────────────────────────────
    UnEntry(
        un_number=2014,
        proper_shipping_name=(
            "HYDROGEN PEROXIDE, AQUEOUS SOLUTION with not less than 20% but not more than 60% "
            "hydrogen peroxide (stabilized as necessary)"
        ),
        class_="5.1", subsidiary_hazard="8", ems="F-H, S-Q",
        rows=(DglRow(
            packing_group="II", special_provisions="", limited_quantity="1 L",
            excepted_quantity="E2", packagings="P504 (PP10)", ibc="IBC02 (B5)",
            large_packagings="", portable_tanks="T7 (TP2, TP6, TP24)", stowage_category="D",
            stowage_codes="SW1", segregation_group="SGG16",
            segregation_codes="SG16, SG59, SG72",
        ),),
        notes="PP10: the packaging shall be vented. B5: IBCs carry a device to allow venting during transport.",
    ),

    # ── Engines and machinery (ro-ro / car carrier ops) ─────────────────────
    UnEntry(
        un_number=3528,
        proper_shipping_name=(
            "ENGINE, INTERNAL COMBUSTION, FLAMMABLE LIQUID POWERED or ENGINE, FUEL CELL, "
            "FLAMMABLE LIQUID POWERED or MACHINERY, INTERNAL COMBUSTION, FLAMMABLE LIQUID "
            "POWERED or MACHINERY, FUEL CELL, FLAMMABLE LIQUID POWERED"
        ),
        class_="3", ems="F-E, S-E",
        rows=(DglRow(
            packing_group=None, special_provisions="363, 972", limited_quantity="0",
            excepted_quantity="E0", packagings="P005", ibc="", large_packagings="",
            portable_tanks="", stowage_category="E", stowage_codes="SW29",
        ),),
        notes=(
            "SP 363: the entry is used only under SP 363's conditions; engines or machinery "
            "empty of liquid or gaseous fuel and containing no other dangerous goods are not "
            "subject to the Code. SP 972: lithium batteries installed in the engine or machinery."
        ),
    ),
    UnEntry(
        un_number=3529,
        proper_shipping_name=(
            "ENGINE, INTERNAL COMBUSTION, FLAMMABLE GAS POWERED or ENGINE, FUEL CELL, "
            "FLAMMABLE GAS POWERED or MACHINERY, INTERNAL COMBUSTION, FLAMMABLE GAS POWERED "
            "or MACHINERY, FUEL CELL, FLAMMABLE GAS POWERED"
        ),
        class_="2.1", ems="F-D, S-U",
        rows=(DglRow(
            packing_group=None, special_provisions="356, 363, 972", limited_quantity="0",
            excepted_quantity="E0", packagings="P005", ibc="", large_packagings="",
            portable_tanks="", stowage_category="E",
        ),),
        notes=(
            "SP 363 as for UN 3528: engines or machinery empty of fuel and containing no other "
            "dangerous goods are not subject to the Code. SP 356: metal hydride storage systems "
            "are approved by the competent authority before acceptance for transport."
        ),
    ),
]


# ── Public ingest API ────────────────────────────────────────────────────────


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op: data lives in the module, no downloads required.

    The CLI dispatcher (raw_dir-style sources) expects this function and
    aborts ingest if (0, 0) is returned. We return (count_of_entries, 0)
    so the dispatcher proceeds to parse_source.
    """
    _ = failed_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    console.print(
        f"  [cyan]imdg_manual:[/cyan] {len(UN_ENTRIES)} hand-curated UN entries (no download)"
    )
    return len(UN_ENTRIES), 0


def parse_source(raw_dir: Path) -> list[Section]:
    """Convert each curated UN entry into a Section for the ingest pipeline.

    `raw_dir` is unused (no source files to read; data lives in the module).
    Signature kept for compatibility with the ingest CLI dispatch.
    """
    _ = raw_dir  # unused
    sections: list[Section] = []
    for entry in UN_ENTRIES:
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=entry.section_number,
            section_title=entry.section_title,
            full_text=entry.render(),
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number="IMDG 3.2",
            published_date=SOURCE_DATE,
        ))
    logger.info("imdg_manual: produced %d UN entries", len(sections))
    return sections


def get_source_date(raw_dir: Path) -> date:
    _ = raw_dir
    return SOURCE_DATE
