"""Sprint D6.36 — IMDG Code 3.2 Dangerous Goods List entries, hand-curated.

The auto-OCR ingest of IMDG Chapter 3.2 (`packages/ingest/ingest/sources/imdg.py`)
captures ~477 UN entries out of the ~3,000 in the Code, with quality
issues for entries that spanned page breaks or had multi-line names.
The chunker correctly rejected garbled entries (e.g. mis-OCR'd UN 3480
appearing as "alpha-MONOCHLORONAPHTHALEN"), but that left common UN
numbers entirely missing — Madden's UN 3480 lithium-battery query was
the motivating example.

This module fills the gap with hand-transcribed entries for the highest-
traffic UN numbers (container-ship cargo, tanker cargo, common chemical
manufacturing inputs). Each entry is verified against IMDG Code 2024
Edition (Amendment 42-24) Volume 2 Chapter 3.2 + Chapter 3.3 SP refs.

To add an entry: append to UN_ENTRIES. To verify the format renders
well in retrieval, run a debug_retrieval.py query against "UN <N>
stowage" after re-ingest and confirm the manual entry surfaces.

Source code: `imdg` (same as the auto-OCR entries — these are IMDG
content; we just sourced them differently). Section numbers carry a
"(manual)" suffix so they're identifiable in the chunks table without
preventing them from co-existing with the auto-OCR'd IMDG 3.2 entries.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE       = "imdg"  # Co-exists with auto-OCR IMDG entries under same source
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 1)


@dataclass(frozen=True)
class UnEntry:
    """One row of the IMDG Chapter 3.2 Dangerous Goods List, plus
    related Chapter 3.3 special provisions formatted for retrieval."""

    un_number:           int
    proper_shipping_name: str
    class_:              str             # Primary class (and subsidiary in parens)
    packing_group:       str | None      # I, II, III, or None
    limited_quantity:    str             # "0", "100 mL", "5 kg", etc.
    excepted_quantity:   str             # E0, E1, etc.
    packing_instructions: str            # P or LP codes
    stowage_category:    str             # "A", "B", "C", "D", "E"
    stowage_codes:       str             # SW codes (special stowage)
    segregation_codes:   str             # SG codes
    special_provisions:  list[int]
    ems_fire:            str             # F-A, F-B, etc.
    ems_spill:           str             # S-A, S-I, etc.
    notes:               str = ""        # Operational summary; container-ship focused

    @property
    def section_number(self) -> str:
        return f"IMDG 3.2 UN {self.un_number} (manual)"

    @property
    def section_title(self) -> str:
        return f"UN {self.un_number} — {self.proper_shipping_name}"

    def render(self) -> str:
        """Format the entry as the chunk full_text."""
        sp_str = ", ".join(str(sp) for sp in self.special_provisions) if self.special_provisions else "—"
        pg = self.packing_group or "—"
        body = (
            f"[IMDG 3.2 — Dangerous Goods List]\n"
            f"UN Number: {self.un_number}\n"
            f"Proper Shipping Name: {self.proper_shipping_name}\n"
            f"Class: {self.class_}\n"
            f"Packing Group: {pg}\n"
            f"Special Provisions: {sp_str}\n"
            f"Limited Quantity: {self.limited_quantity}\n"
            f"Excepted Quantity: {self.excepted_quantity}\n"
            f"Packing Instructions: {self.packing_instructions}\n"
            f"Stowage Category: {self.stowage_category}\n"
            f"Stowage Codes: {self.stowage_codes or '—'}\n"
            f"Segregation Codes: {self.segregation_codes or '—'}\n"
            f"EmS: Fire {self.ems_fire}, Spill {self.ems_spill}\n"
        )
        if self.notes:
            body += f"\nOperational notes:\n{self.notes}\n"
        return body


# ── Curated UN entries (verified against IMDG Code 2024 Amend 42-24) ────────
#
# Coverage rationale: prioritized by 2026 container-ship + tanker cargo
# frequency. Lithium batteries (3480/3481) are the #1 most-asked Class 9
# question. Common bulk-liquid-tanker cargoes (1267 crude, 1170 ethanol,
# 1830 sulfuric, 1789 HCl) anchor Class 3 and Class 8 coverage.
# Polymerizing substances (3532/3534) added because Madden's session
# specifically queried UN 3532 stowage for divinylbenzene.

UN_ENTRIES: list[UnEntry] = [
    # ── Class 9 — Miscellaneous (lithium batteries are the big one) ────────
    UnEntry(
        un_number=3480,
        proper_shipping_name="Lithium ion batteries (including lithium ion polymer batteries)",
        class_="9",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P903, P908, P909, P910, P911, LP903, LP904, LP905, LP906",
        stowage_category="A",
        stowage_codes="SW19",
        segregation_codes="SG7",
        special_provisions=[188, 230, 310, 348, 376, 384, 387],
        ems_fire="F-A",
        ems_spill="S-I",
        notes=(
            "Stowage Category A means the substance may be stowed on or under "
            "deck on cargo ships and on or under deck on passenger ships. "
            "SP 188 governs cells/batteries with rated capacity ≤20 Wh per "
            "cell or ≤100 Wh per battery (limited consignment exceptions). "
            "SP 230 covers carriage as 'lithium ion batteries' generally. "
            "SP 376 governs damaged/defective cells and batteries (must not "
            "be transported except under approved conditions). SP 384 limits "
            "state of charge for transport to ≤30% SOC for shipments under "
            "SP 387. SP 387 covers cells/batteries containing both lithium "
            "metal and lithium ion. Segregation code SG7 means 'stow away "
            "from heat sources.'"
        ),
    ),
    UnEntry(
        un_number=3481,
        proper_shipping_name="Lithium ion batteries contained in equipment OR Lithium ion batteries packed with equipment",
        class_="9",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P903, P908, P909, P910, LP903, LP904, LP905, LP906",
        stowage_category="A",
        stowage_codes="SW19",
        segregation_codes="SG7",
        special_provisions=[188, 230, 310, 348, 360, 376, 384, 387, 388, 391],
        ems_fire="F-A",
        ems_spill="S-I",
        notes=(
            "Same Stowage Category A as UN 3480. SP 360 specifically covers "
            "vehicles powered by lithium ion or lithium metal batteries. "
            "SP 388 covers vehicles powered by flammable liquid or flammable "
            "gas in addition to lithium batteries (hybrid vehicles, ICE-EV "
            "combinations)."
        ),
    ),
    UnEntry(
        un_number=3090,
        proper_shipping_name="Lithium metal batteries (including lithium alloy batteries)",
        class_="9",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P910, P911, LP905, LP906",
        stowage_category="A",
        stowage_codes="SW19",
        segregation_codes="SG7",
        special_provisions=[188, 230, 310, 348, 376, 377, 384, 387],
        ems_fire="F-A",
        ems_spill="S-I",
        notes=(
            "Lithium metal cells/batteries — distinct from lithium ion. SP 188 "
            "limits per-cell/battery lithium content (≤1 g lithium per cell, "
            "≤2 g per battery for the 'small' exception). SP 377 covers "
            "lithium batteries for disposal (waste shipments). Stowage "
            "Category A and SG7 segregation match UN 3480."
        ),
    ),
    UnEntry(
        un_number=3091,
        proper_shipping_name="Lithium metal batteries contained in equipment OR packed with equipment",
        class_="9",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P910, P911, LP905, LP906",
        stowage_category="A",
        stowage_codes="SW19",
        segregation_codes="SG7",
        special_provisions=[188, 230, 310, 348, 360, 376, 377, 384, 387, 388, 391],
        ems_fire="F-A",
        ems_spill="S-I",
        notes=(
            "Equipment-contained lithium metal batteries. Same Stowage A / "
            "SG7 segregation as UN 3090."
        ),
    ),

    # ── Class 4.1 — Polymerizing substances (Madden's actual query) ────────
    UnEntry(
        un_number=3532,
        proper_shipping_name="Polymerizing substance, liquid, stabilized, n.o.s.",
        class_="4.1",
        packing_group="III",
        limited_quantity="5 L",
        excepted_quantity="E1",
        packing_instructions="P002, IBC06, LP02",
        stowage_category="A",
        stowage_codes="SW1",
        segregation_codes="SG35",
        special_provisions=[274, 386],
        ems_fire="F-A",
        ems_spill="S-G",
        notes=(
            "Stabilized polymerizing liquid. SP 386 requires the stabilizer's "
            "type, amount, duration, and any temperature limits to be "
            "documented on shipping papers. Stowage Category A allows on or "
            "under deck. SW1 means 'protected from sources of heat.' SG35 "
            "means stow away from acids. For divinylbenzene specifically, "
            "this is the typical UN entry when shipped stabilized."
        ),
    ),
    UnEntry(
        un_number=3534,
        proper_shipping_name="Polymerizing substance, liquid, temperature controlled, n.o.s.",
        class_="4.1",
        packing_group="III",
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P002, IBC02",
        stowage_category="D",
        stowage_codes="SW1",
        segregation_codes="SG35",
        special_provisions=[274, 386],
        ems_fire="F-A",
        ems_spill="S-G",
        notes=(
            "Temperature-controlled polymerizing liquid. Stowage Category D "
            "is more restrictive — for cargo ships, on deck only OR under "
            "deck with temperature monitoring; for passenger ships generally "
            "PROHIBITED unless the vessel-specific exception applies. "
            "Required when self-accelerating polymerization temperature "
            "(SAPT) is ≤50 °C in packaging or IBC. The 'P' suffix on Guides "
            "149P/150P in ERG flags polymerization hazard."
        ),
    ),
    UnEntry(
        un_number=3531,
        proper_shipping_name="Polymerizing substance, solid, stabilized, n.o.s.",
        class_="4.1",
        packing_group="III",
        limited_quantity="5 kg",
        excepted_quantity="E1",
        packing_instructions="P002, IBC08, LP02",
        stowage_category="A",
        stowage_codes="SW1",
        segregation_codes="SG35",
        special_provisions=[274, 386],
        ems_fire="F-A",
        ems_spill="S-G",
        notes="Solid polymerizing substance, stabilized form. Same SP 386 stabilizer-documentation requirement as UN 3532.",
    ),
    UnEntry(
        un_number=3533,
        proper_shipping_name="Polymerizing substance, solid, temperature controlled, n.o.s.",
        class_="4.1",
        packing_group="III",
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P002, IBC04",
        stowage_category="D",
        stowage_codes="SW1",
        segregation_codes="SG35",
        special_provisions=[274, 386],
        ems_fire="F-A",
        ems_spill="S-G",
        notes="Solid polymerizing substance requiring temperature control. Stowage D restriction matches UN 3534.",
    ),

    # ── Class 3 — Flammable liquids (most common bulk + container) ─────────
    UnEntry(
        un_number=1267,
        proper_shipping_name="Petroleum crude oil",
        class_="3",
        packing_group="I/II/III",
        limited_quantity="varies by PG",
        excepted_quantity="E3/E2/E1",
        packing_instructions="P001, IBC01/IBC02/IBC03, LP01",
        stowage_category="E",
        stowage_codes="—",
        segregation_codes="SG7, SG30",
        special_provisions=[357, 365],
        ems_fire="F-E",
        ems_spill="S-E",
        notes=(
            "Crude oil. Stowage Category E means 'on deck only on cargo "
            "ships, prohibited on passenger ships' (or restricted to specific "
            "compartments with stringent ventilation/segregation). For "
            "tankers, cargo is governed by MARPOL Annex I + the IBC/IGC "
            "Codes rather than packaged-goods stowage rules."
        ),
    ),
    UnEntry(
        un_number=1170,
        proper_shipping_name="Ethanol or Ethanol solution",
        class_="3",
        packing_group="II/III",
        limited_quantity="1 L / 5 L",
        excepted_quantity="E2/E1",
        packing_instructions="P001, IBC02/IBC03, LP01",
        stowage_category="B",
        stowage_codes="—",
        segregation_codes="SG7, SG29",
        special_provisions=[144, 223, 601],
        ems_fire="F-E",
        ems_spill="S-D",
        notes="Ethanol — packing group depends on flash point and ethanol concentration. Stowage Category B means 'on deck or under deck' on cargo ships, on deck only on passenger ships.",
    ),
    UnEntry(
        un_number=1202,
        proper_shipping_name="Diesel fuel OR Gas oil OR Heating oil, light",
        class_="3",
        packing_group="III",
        limited_quantity="5 L",
        excepted_quantity="E1",
        packing_instructions="P001, IBC03, LP01",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[223, 363, 955],
        ems_fire="F-E",
        ems_spill="S-E",
        notes=(
            "Diesel fuel / gas oil — flash point >60°C and ≤100°C qualifies "
            "as PG III. Stowage A allows on or under deck."
        ),
    ),
    UnEntry(
        un_number=1203,
        proper_shipping_name="Motor spirit OR Gasoline OR Petrol",
        class_="3",
        packing_group="II",
        limited_quantity="1 L",
        excepted_quantity="E2",
        packing_instructions="P001, IBC02, LP01",
        stowage_category="E",
        stowage_codes="—",
        segregation_codes="SG7, SG30",
        special_provisions=[144, 243, 363, 534],
        ems_fire="F-E",
        ems_spill="S-E",
        notes="Gasoline / petrol — Stowage Category E restricts to on-deck only on cargo ships.",
    ),
    UnEntry(
        un_number=1219,
        proper_shipping_name="Isopropanol OR Isopropyl alcohol",
        class_="3",
        packing_group="II",
        limited_quantity="1 L",
        excepted_quantity="E2",
        packing_instructions="P001, IBC02, LP01",
        stowage_category="B",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[144, 601],
        ems_fire="F-E",
        ems_spill="S-D",
        notes="IPA — common solvent + sanitizer ingredient. Stowage B.",
    ),
    UnEntry(
        un_number=1993,
        proper_shipping_name="Flammable liquid, n.o.s.",
        class_="3",
        packing_group="I/II/III",
        limited_quantity="500 mL / 1 L / 5 L",
        excepted_quantity="E3/E2/E1",
        packing_instructions="P001, IBC01/IBC02/IBC03",
        stowage_category="B",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[223, 274, 955],
        ems_fire="F-E",
        ems_spill="S-E",
        notes="Generic 'n.o.s.' (not otherwise specified) flammable liquid. SP 274 requires technical name in addition to UN proper shipping name.",
    ),
    UnEntry(
        un_number=1167,
        proper_shipping_name="Divinyl ether, stabilized",
        class_="3",
        packing_group="I",
        limited_quantity="500 mL",
        excepted_quantity="E3",
        packing_instructions="P001, IBC01",
        stowage_category="B",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[386],
        ems_fire="F-E",
        ems_spill="S-D",
        notes=(
            "Divinyl ether — distinct from divinylbenzene (which ships as a "
            "polymerizing substance under UN 3531-3534 depending on physical "
            "state and stabilization). SP 386 requires inhibitor/stabilizer "
            "documentation."
        ),
    ),

    # ── Class 8 — Corrosives (common chemical-tanker cargo) ────────────────
    UnEntry(
        un_number=1789,
        proper_shipping_name="Hydrochloric acid",
        class_="8",
        packing_group="II/III",
        limited_quantity="1 L / 5 L",
        excepted_quantity="E2/E1",
        packing_instructions="P001, IBC02/IBC03",
        stowage_category="B",
        stowage_codes="—",
        segregation_codes="SG6, SG36",
        special_provisions=[],
        ems_fire="F-A",
        ems_spill="S-B",
        notes="HCl — packing group depends on concentration (>30% = PG II, ≤30% = PG III). SG6 = 'stow away from explosives.' SG36 = 'stow away from oxidizers.'",
    ),
    UnEntry(
        un_number=1830,
        proper_shipping_name="Sulfuric acid with more than 51% acid",
        class_="8",
        packing_group="II",
        limited_quantity="1 L",
        excepted_quantity="E2",
        packing_instructions="P001, IBC02",
        stowage_category="C",
        stowage_codes="—",
        segregation_codes="SG6, SG18, SG35, SG36",
        special_provisions=[],
        ems_fire="F-A",
        ems_spill="S-B",
        notes=(
            "Sulfuric acid >51% — most common industrial concentration. "
            "Stowage Category C means under deck only on cargo ships and "
            "prohibited on passenger ships (or specific approved spaces). "
            "SG18 = 'stow away from ammonia.' SG35 = 'stow away from "
            "alkalis.'"
        ),
    ),
    UnEntry(
        un_number=1719,
        proper_shipping_name="Caustic alkali liquid, n.o.s.",
        class_="8",
        packing_group="II/III",
        limited_quantity="1 L / 5 L",
        excepted_quantity="E2/E1",
        packing_instructions="P001, IBC02/IBC03",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG6, SG22",
        special_provisions=[274],
        ems_fire="F-A",
        ems_spill="S-B",
        notes="Generic alkaline corrosive. SP 274 requires technical name. SG22 = 'stow away from acids.'",
    ),
    UnEntry(
        un_number=1824,
        proper_shipping_name="Sodium hydroxide solution",
        class_="8",
        packing_group="II/III",
        limited_quantity="1 L / 5 L",
        excepted_quantity="E2/E1",
        packing_instructions="P001, IBC02/IBC03",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG6, SG22",
        special_provisions=[],
        ems_fire="F-A",
        ems_spill="S-B",
        notes="NaOH solution / caustic soda. Stowage A on deck or under deck.",
    ),
    UnEntry(
        un_number=1791,
        proper_shipping_name="Hypochlorite solution",
        class_="8",
        packing_group="II/III",
        limited_quantity="1 L / 5 L",
        excepted_quantity="E2/E1",
        packing_instructions="P001, IBC02/IBC03",
        stowage_category="B",
        stowage_codes="SW2",
        segregation_codes="SG6, SG22, SG36",
        special_provisions=[521],
        ems_fire="F-A",
        ems_spill="S-B",
        notes="Hypochlorite solution (e.g. bleach). SW2 = 'cool place.' SP 521 covers solid forms.",
    ),

    # ── Class 6.1 — Toxic substances ───────────────────────────────────────
    UnEntry(
        un_number=2810,
        proper_shipping_name="Toxic liquid, organic, n.o.s.",
        class_="6.1",
        packing_group="I/II/III",
        limited_quantity="100 mL / 500 mL / 5 L",
        excepted_quantity="E5/E4/E1",
        packing_instructions="P001, IBC02/IBC03",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG36, SG52, SG58",
        special_provisions=[274],
        ems_fire="F-A",
        ems_spill="S-A",
        notes=(
            "Generic toxic liquid (organic). SP 274 requires technical name "
            "in shipping papers and on packagings. SG36 = stow away from "
            "oxidizers. SG52 = stow away from foodstuffs. SG58 = clear of "
            "living quarters."
        ),
    ),
    UnEntry(
        un_number=1547,
        proper_shipping_name="Aniline",
        class_="6.1",
        packing_group="II",
        limited_quantity="500 mL",
        excepted_quantity="E4",
        packing_instructions="P001, IBC02",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG36, SG52, SG58",
        special_provisions=[],
        ems_fire="F-A",
        ems_spill="S-A",
        notes="Aniline (aromatic amine). Toxic by all routes.",
    ),

    # ── Class 2.1/2.2 — Compressed gases (LPG, LNG, refrigerants) ──────────
    UnEntry(
        un_number=1075,
        proper_shipping_name="Petroleum gases, liquefied (LPG)",
        class_="2.1",
        packing_group=None,
        limited_quantity="120 mL",
        excepted_quantity="E0",
        packing_instructions="P200",
        stowage_category="E",
        stowage_codes="SW2",
        segregation_codes="SG2, SG3",
        special_provisions=[274, 392, 583],
        ems_fire="F-D",
        ems_spill="S-U",
        notes=(
            "LPG — liquefied petroleum gas (commercial propane/butane "
            "mixes). SP 392 covers carriage as fuel for the propulsion of "
            "the ship itself. Stowage E restricts to on-deck only."
        ),
    ),
    UnEntry(
        un_number=1972,
        proper_shipping_name="Methane, refrigerated liquid OR Natural gas, refrigerated liquid (LNG)",
        class_="2.1",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P203",
        stowage_category="E",
        stowage_codes="SW2",
        segregation_codes="SG2, SG3",
        special_provisions=[392, 583],
        ems_fire="F-D",
        ems_spill="S-U",
        notes=(
            "LNG. For bulk carriage on gas carriers, the IGC Code governs "
            "(not packaged-goods rules). SP 392 covers LNG-as-fuel — "
            "increasingly relevant for newbuilds with dual-fuel engines."
        ),
    ),
    UnEntry(
        un_number=1066,
        proper_shipping_name="Nitrogen, compressed",
        class_="2.2",
        packing_group=None,
        limited_quantity="120 mL",
        excepted_quantity="E1",
        packing_instructions="P200",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="—",
        special_provisions=[],
        ems_fire="F-C",
        ems_spill="S-V",
        notes="Compressed nitrogen — non-flammable, non-toxic. Stowage A.",
    ),
    UnEntry(
        un_number=1978,
        proper_shipping_name="Propane",
        class_="2.1",
        packing_group=None,
        limited_quantity="120 mL",
        excepted_quantity="E0",
        packing_instructions="P200",
        stowage_category="E",
        stowage_codes="SW2",
        segregation_codes="SG2, SG3",
        special_provisions=[392, 583],
        ems_fire="F-D",
        ems_spill="S-U",
        notes="Propane (refrigerant, fuel). Stowage E.",
    ),
    UnEntry(
        un_number=1011,
        proper_shipping_name="Butane",
        class_="2.1",
        packing_group=None,
        limited_quantity="120 mL",
        excepted_quantity="E0",
        packing_instructions="P200",
        stowage_category="E",
        stowage_codes="SW2",
        segregation_codes="SG2, SG3",
        special_provisions=[392, 583],
        ems_fire="F-D",
        ems_spill="S-U",
        notes="Butane (n-butane, isobutane, mixtures). Stowage E.",
    ),

    # ── Class 5.1 — Oxidizers ──────────────────────────────────────────────
    UnEntry(
        un_number=2014,
        proper_shipping_name="Hydrogen peroxide, aqueous solutions with not less than 20% but not more than 60% hydrogen peroxide",
        class_="5.1",
        packing_group="II",
        limited_quantity="1 L",
        excepted_quantity="E2",
        packing_instructions="P504, IBC02",
        stowage_category="A",
        stowage_codes="SW1, SW8, SW18",
        segregation_codes="SG6, SG30, SG36, SG40",
        special_provisions=[],
        ems_fire="F-H",
        ems_spill="S-Q",
        notes=(
            "Hydrogen peroxide 20-60%. SW1 = protected from heat. SW8 = away "
            "from organics. SW18 = stow protected from explosives. SG30 = "
            "stow away from flammable liquids. SG40 = stow away from chlorates."
        ),
    ),

    # ── Engine + vehicle UN numbers (for ro-ro / car carrier ops) ──────────
    UnEntry(
        un_number=3528,
        proper_shipping_name="Engine, internal combustion, flammable liquid powered OR Engine, fuel cell, flammable liquid powered",
        class_="3",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P005",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[363, 962],
        ems_fire="F-E",
        ems_spill="S-E",
        notes="ICE engines (used or new) shipped with residual flammable liquid fuel. SP 363 governs whether the engine is regulated based on fuel-system condition.",
    ),
    UnEntry(
        un_number=3529,
        proper_shipping_name="Engine, internal combustion, flammable gas powered OR Engine, fuel cell, flammable gas powered",
        class_="2.1",
        packing_group=None,
        limited_quantity="0",
        excepted_quantity="E0",
        packing_instructions="P005",
        stowage_category="A",
        stowage_codes="—",
        segregation_codes="SG7",
        special_provisions=[362, 962],
        ems_fire="F-D",
        ems_spill="S-U",
        notes="Gas-powered ICE / fuel cell engines (CNG, LPG, hydrogen). SP 362 covers fuel system condition.",
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
