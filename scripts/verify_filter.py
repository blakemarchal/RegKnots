"""Direct test: call _filter_by_vessel_applicability on known-contaminated
retrieval candidates, confirm it drops the right chunks."""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

sys.path.insert(0, "/opt/RegKnots/packages/rag")

from rag.retriever import _filter_by_vessel_applicability  # noqa: E402

# Synthetic candidates mimicking what the retriever would produce for a
# containership SCBA query: a mix of applicable (Part 95/96/160/161 +
# SOLAS/NVIC) and forbidden (Part 35/77/117/180/195) chunks.
candidates = [
    {"source": "cfr_46", "section_number": "46 CFR 96.35-10", "similarity": 0.80, "full_text": "Fireman's outfit cargo"},
    {"source": "cfr_46", "section_number": "46 CFR 77.35-10", "similarity": 0.79, "full_text": "Fireman's outfit passenger"},
    {"source": "cfr_46", "section_number": "46 CFR 117.175", "similarity": 0.78, "full_text": "Survival craft equipment T"},
    {"source": "cfr_46", "section_number": "46 CFR 180.175", "similarity": 0.77, "full_text": "Survival craft equipment T"},
    {"source": "cfr_46", "section_number": "46 CFR 195.35-10", "similarity": 0.76, "full_text": "Fireman's outfit research"},
    {"source": "cfr_46", "section_number": "46 CFR 142.226", "similarity": 0.75, "full_text": "Fireman's outfit towing M"},
    {"source": "cfr_46", "section_number": "46 CFR 35.30-20", "similarity": 0.74, "full_text": "Emergency outfit tank D"},
    {"source": "cfr_46", "section_number": "46 CFR 160.156-7", "similarity": 0.73, "full_text": "Rescue boat specs (UNIVERSAL)"},
    {"source": "solas",  "section_number": "SOLAS Ch.II-2 Part E", "similarity": 0.72, "full_text": "SOLAS"},
    {"source": "nvic",   "section_number": "NVIC 06-93 §3",      "similarity": 0.71, "full_text": "NVIC"},
]

print("=== Input (10 candidates) ===")
for c in candidates:
    print(f"  [{c['source']}] {c['section_number']}")

print()
print("=== After filter with vessel_type='Containership' ===")
filtered = _filter_by_vessel_applicability(
    list(candidates), {"vessel_type": "Containership"},
)
for c in filtered:
    print(f"  [{c['source']}] {c['section_number']}")
print(f"Kept {len(filtered)}/{len(candidates)}")

print()
print("=== After filter with vessel_type='Tanker' ===")
filtered = _filter_by_vessel_applicability(
    list(candidates), {"vessel_type": "Tanker"},
)
for c in filtered:
    print(f"  [{c['source']}] {c['section_number']}")
print(f"Kept {len(filtered)}/{len(candidates)}")

print()
print("=== After filter with vessel_type='Towing / Tugboat' ===")
filtered = _filter_by_vessel_applicability(
    list(candidates), {"vessel_type": "Towing / Tugboat"},
)
for c in filtered:
    print(f"  [{c['source']}] {c['section_number']}")
print(f"Kept {len(filtered)}/{len(candidates)}")

print()
print("=== After filter with vessel_type='Research Vessel' ===")
filtered = _filter_by_vessel_applicability(
    list(candidates), {"vessel_type": "Research Vessel"},
)
for c in filtered:
    print(f"  [{c['source']}] {c['section_number']}")
print(f"Kept {len(filtered)}/{len(candidates)}")

print()
print("=== No vessel_profile (should be no-op) ===")
filtered = _filter_by_vessel_applicability(list(candidates), None)
print(f"Kept {len(filtered)}/{len(candidates)}")
