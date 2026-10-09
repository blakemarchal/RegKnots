"""2026-10-08 — jurisdiction tag drift check (ingest.tag_check)."""
from ingest.tag_check import drift


def test_drift_reports_only_mismatched_groups():
    rows = [
        {"source": "cfr_46", "jurisdictions": ["us"], "n": 10},
        {"source": "coswp", "jurisdictions": ["intl"], "n": 660},      # the 2026-10-08 case
        {"source": "coswp", "jurisdictions": ["uk"], "n": 3},
        {"source": "made_up_source", "jurisdictions": ["intl"], "n": 1},  # unknown source defaults to intl
    ]
    assert drift(rows) == [("coswp", ["intl"], ["uk"], 660)]
