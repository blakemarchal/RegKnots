"""Capitanerie di Porto + MIT (Italy) — adapter wrapper. See flag_curated.py."""

from ingest.sources.flag_curated import make_adapter

_adapter = make_adapter("it_capitaneria")

SOURCE       = _adapter.SOURCE
TITLE_NUMBER = _adapter.TITLE_NUMBER
SOURCE_DATE  = _adapter.SOURCE_DATE

discover_and_download = _adapter.discover_and_download
parse_source          = _adapter.parse_source
get_source_date       = _adapter.get_source_date
