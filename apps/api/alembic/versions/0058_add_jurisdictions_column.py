"""add jurisdictions column to regulations

Revision ID: 0058
Revises: 0057
Create Date: 2026-04-28

Sprint D6.19 — D3 architecture for multi-flag corpus severance.

Goal: a US-flag query must mathematically not surface UK / AU / LR /
MI / etc. chunks unless the user explicitly invokes that jurisdiction
in the query text. Same in reverse for foreign-flag queries.

The implementation is an additive allow-list intersected at retrieval
time. Each chunk carries `jurisdictions text[]` listing the
flag-state(s) under which it is binding or authoritative. The
retriever computes a per-query allow-set from:

  1. base       — always {'intl'}  (universal sources: SOLAS, COLREGs,
                  STCW, ISM, MARPOL, IMDG, WHO IHR — bind every flag)
  2. flag       — derived from vessel_profile.flag_state, e.g. {'us'}
  3. query      — explicit references in the query text ("33 CFR",
                  "MGN 71", "USCG", "MCA") add their jurisdiction(s)

A chunk is retrievable iff `chunk.jurisdictions && allowed_set` is
non-empty (PostgreSQL array overlap operator).

Backfill mapping for existing sources (executed below):

  ['us']         — cfr_33, cfr_46, cfr_49, usc_46, nvic, nmc_policy,
                   nmc_checklist, uscg_msm, uscg_bulletin
  ['uk']         — mca_mgn, mca_msn
  ['intl']       — solas, solas_supplement, colregs, stcw,
                   stcw_supplement, ism, ism_supplement, marpol,
                   marpol_supplement, imdg, imdg_supplement, who_ihr
  ['us','intl']  — erg  (US DOT publication, but referenced
                   internationally as the de-facto first-responder
                   guide; tagged dual so it surfaces under any flag)

GIN index on jurisdictions makes the && filter O(log N) per query.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Source → jurisdiction tags. KEEP IN SYNC with the runtime mapping in
# packages/rag/rag/jurisdiction.py — both are authoritative for their
# layer (DB at write time, runtime for new sources at read time).
_SOURCE_TO_JURISDICTIONS: dict[str, list[str]] = {
    # US national
    "cfr_33":           ["us"],
    "cfr_46":           ["us"],
    "cfr_49":           ["us"],
    "usc_46":           ["us"],
    "nvic":             ["us"],
    "nmc_policy":       ["us"],
    "nmc_checklist":    ["us"],
    "uscg_msm":         ["us"],
    "uscg_bulletin":    ["us"],
    # UK national
    "mca_mgn":          ["uk"],
    "mca_msn":          ["uk"],
    # International (universal — bind every flag on int'l voyages)
    "solas":            ["intl"],
    "solas_supplement": ["intl"],
    "colregs":          ["intl"],
    "stcw":             ["intl"],
    "stcw_supplement":  ["intl"],
    "ism":              ["intl"],
    "ism_supplement":   ["intl"],
    "marpol":           ["intl"],
    "marpol_supplement":["intl"],
    "imdg":             ["intl"],
    "imdg_supplement":  ["intl"],
    "who_ihr":          ["intl"],
    # Dual-tagged: ERG is a US DOT publication BUT is the de-facto
    # international first-responder reference for hazmat. Tagging dual
    # so it surfaces for both US-flag and non-US-flag UN-number queries.
    "erg":              ["us", "intl"],
}


def upgrade() -> None:
    # 1. Add the column with a placeholder default. We'll backfill
    #    per-source below, then drop the default so future inserts must
    #    set jurisdictions explicitly (caught at the application layer).
    op.add_column(
        "regulations",
        sa.Column(
            "jurisdictions",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['intl']::text[]"),
        ),
    )

    # 2. Backfill from the source-to-jurisdiction map.
    for source, juris in _SOURCE_TO_JURISDICTIONS.items():
        # PostgreSQL array literal: ARRAY['us'] / ARRAY['us','intl']
        array_literal = "ARRAY[" + ",".join(f"'{j}'" for j in juris) + "]::text[]"
        op.execute(
            f"UPDATE regulations SET jurisdictions = {array_literal} "
            f"WHERE source = '{source}'"
        )

    # 3. Drop the server default — application layer is now authoritative.
    op.alter_column("regulations", "jurisdictions", server_default=None)

    # 4. GIN index for fast && (array overlap) lookups at retrieval time.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulations_jurisdictions "
        "ON regulations USING GIN (jurisdictions)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_regulations_jurisdictions")
    op.drop_column("regulations", "jurisdictions")
