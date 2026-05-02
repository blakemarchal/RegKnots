from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ── Source constants ────────────────────────────────────────────────────────

SOURCE_TO_TITLE: dict[str, int] = {
    "cfr_33": 33,
    "cfr_46": 46,
    "cfr_49": 49,
}

TITLE_TO_SOURCE: dict[int, str] = {v: k for k, v in SOURCE_TO_TITLE.items()}

TITLE_NAMES: dict[int, str] = {
    33: "Title 33—Navigation and Navigable Waters",
    46: "Title 46—Shipping",
    49: "Title 49—Transportation",
    # Non-CFR sources use title_number=0
    0: "COLREGs — International/Inland Navigation Rules",
}

# Sources ingested from text/PDF/XML files (not eCFR API). title_number=0 for all.
PDF_SOURCES: list[str] = ["amsa_mo", "bg_verkehr", "bma_mn", "colregs", "dgmm_es", "erg", "fr_transport", "gr_ynanp", "iacs_pr", "iacs_ur", "imdg", "imdg_manual", "imdg_supplement", "imo_bwm", "imo_css", "imo_hsc", "imo_iamsar", "imo_ibc", "imo_igc", "imo_igf", "imo_loadlines", "imo_polar", "iri_mn", "ism", "ism_supplement", "it_capitaneria", "liscr_mn", "mardep_msin", "marpol", "marpol_amend", "marpol_supplement", "mca_mgn", "mca_msn", "mou_psc", "mpa_sc", "nma_rsv", "nmc_checklist", "nmc_policy", "nvic", "ocimf", "solas", "solas_supplement", "stcw", "stcw_amend", "stcw_supplement", "tc_ssb", "usc_46", "uscg_bulletin", "uscg_msm", "who_ihr"]


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class Section:
    """A regulation section extracted from eCFR XML."""
    source: str                          # "cfr_33" | "cfr_46" | "cfr_49"
    title_number: int                    # 33 | 46 | 49
    section_number: str                  # "33 CFR 1.01-1"
    section_title: str                   # "Purpose of part."
    full_text: str                       # raw extracted text (no section prefix)
    up_to_date_as_of: date
    parent_section_number: Optional[str] = None  # e.g. "33 CFR Part 1"
    # Freshness metadata (added in migration 0045). Only uscg_bulletin
    # populates these today; other sources leave them None.
    published_date: Optional[date] = None
    expires_date: Optional[date] = None
    superseded_by: Optional[str] = None
    # ISO 639-1 language code (added migration 0070). Defaults to "en"
    # so existing English-only adapters keep working unchanged.
    language: str = "en"


@dataclass
class Chunk:
    """A token-bounded slice of a Section, ready for embedding."""
    source: str
    title_number: int
    section_number: str
    section_title: str
    chunk_index: int
    chunk_text: str                      # section header prefix + content slice
    content_hash: str                    # sha256(chunk_text)
    token_count: int
    up_to_date_as_of: date
    parent_section_number: Optional[str] = None
    published_date: Optional[date] = None
    expires_date: Optional[date] = None
    superseded_by: Optional[str] = None
    language: str = "en"


@dataclass
class EmbeddedChunk:
    """A Chunk plus its embedding vector."""
    source: str
    title_number: int
    section_number: str
    section_title: str
    chunk_index: int
    chunk_text: str
    content_hash: str
    token_count: int
    up_to_date_as_of: date
    embedding: list[float]
    parent_section_number: Optional[str] = None
    published_date: Optional[date] = None
    expires_date: Optional[date] = None
    superseded_by: Optional[str] = None
    language: str = "en"


@dataclass
class IngestResult:
    """Summary of a single-source pipeline run."""
    source: str
    sections_found: int = 0
    chunks_created: int = 0
    chunks_skipped: int = 0       # already in DB with matching hash
    embeddings_generated: int = 0
    upserts: int = 0
    # Mode-independent count of chunks whose content_hash is not already in the
    # DB for this source — i.e. rows that will be NEW or MODIFIED after upsert.
    # Used to gate auto-notifications on real content changes.
    new_or_modified_chunks: int = 0
    # Net change in chunk count for this source (chunks_after - chunks_before).
    # Positive = net adds, negative = net removals, 0 = pure updates or no-op.
    net_chunk_delta: int = 0
    version_changes: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)
