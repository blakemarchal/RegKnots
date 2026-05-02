"""OCIMF public-layer (SIRE 2.0 + Information Papers) — adapter wrapper.
See flag_curated.py for the shared download/parse logic and the
curated PDF list. Sprint D6.50."""

from ingest.sources.flag_curated import make_adapter

_adapter = make_adapter("ocimf")

SOURCE       = _adapter.SOURCE
TITLE_NUMBER = _adapter.TITLE_NUMBER
SOURCE_DATE  = _adapter.SOURCE_DATE

discover_and_download = _adapter.discover_and_download
parse_source          = _adapter.parse_source
get_source_date       = _adapter.get_source_date
