"""
TOC manifests for the knowledge-base audit tool.

Each YAML file in this directory describes the expected structural sections
for one regulation source. The audit tool loads these to check the live
database for missing, truncated, or unembedded content.

Sources that are too large for a static manifest (cfr_33/46/49, nvic) do
not have a YAML file here — the audit falls back to a DB-only sanity check
(embedding gaps, suspiciously short chunks).
"""
