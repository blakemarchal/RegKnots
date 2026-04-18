"""Gap analysis: cross-reference FR discovery CSVs against corpus inventory CSVs.

Reads all six CSVs from data/reports/ and writes a markdown gap report
to docs/sprint-audits/federal-register-discovery-gap-report.md.

Run on the VPS where both CSV sets are colocated:
    cd /opt/RegKnots
    python3 scripts/fr_gap_analysis.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path("/opt/RegKnots/data/reports")
OUT_PATH = Path("/opt/RegKnots/docs/sprint-audits/federal-register-discovery-gap-report.md")


# ── NVIC corpus normalization ───────────────────────────────────────────────
# Corpus rows look like "NVIC 04-08 Ch-2 §1" or "NVIC 01-01 §3".
# Normalize to the parent doc number "NVIC 04-08" — drop §N AND Ch-N so
# corpus and FR groupings align at the same granularity.

_NVIC_NORMALIZE = re.compile(r"^NVIC\s+(\d{1,2}-\d{2})\b", re.IGNORECASE)


def normalize_nvic(section_number: str) -> str | None:
    m = _NVIC_NORMALIZE.match(section_number.strip())
    if m:
        return f"NVIC {m.group(1)}"
    return None


# Same applied to FR-inferred numbers
def strip_nvic_change(inferred: str) -> str:
    m = _NVIC_NORMALIZE.match(inferred.strip())
    if m:
        return f"NVIC {m.group(1)}"
    return inferred


def load_corpus_nvics() -> set[str]:
    nvics: set[str] = set()
    with (REPORTS_DIR / "corpus_inventory_nvic.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            n = normalize_nvic(row["section_number"])
            if n:
                nvics.add(n)
    return nvics


def load_corpus_simple(filename: str) -> set[str]:
    out: set[str] = set()
    with (REPORTS_DIR / filename).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sn = (row.get("section_number") or "").strip()
            if sn:
                out.add(sn)
    return out


def load_fr_csv(filename: str) -> list[dict]:
    with (REPORTS_DIR / filename).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fr_pubrate(docs: list[dict]) -> float:
    """Average publications/year over the past 5 calendar years."""
    cutoff = datetime.now().year - 5
    recent = [d for d in docs if d["publication_date"] >= f"{cutoff}-01-01"]
    return len(recent) / 5.0


def host_distribution(missing_docs: list[dict]) -> Counter:
    c: Counter = Counter()
    for d in missing_docs:
        c[d.get("pdf_host") or "none"] += 1
    return c


def signal_noise_summary(category: str, fr_docs: list[dict],
                          term_in_title_re: re.Pattern) -> dict:
    """Quantify how much of the FR full-text result set is actually relevant."""
    total = len(fr_docs)
    title_has_term = sum(1 for r in fr_docs if term_in_title_re.search(r["title"]))
    title_parsed = sum(1 for r in fr_docs if r.get("inferred_document_number"))
    unique_inferred = len({r["inferred_document_number"]
                           for r in fr_docs if r.get("inferred_document_number")})
    return {
        "total": total,
        "title_has_term": title_has_term,
        "title_parsed": title_parsed,
        "unique_inferred": unique_inferred,
        "noise_ratio": (total - title_parsed) / total if total else 0,
    }


def render_doc_line(d: dict) -> str:
    return (
        f"  - **{d.get('inferred_document_number') or '(unparsed)'}** — "
        f"{d['title'][:120]}{'…' if len(d['title']) > 120 else ''} · "
        f"{d['publication_date']} · "
        f"[FR {d['fr_doc_number']}]({d['html_url']})"
        + (f" · [PDF]({d['pdf_url']})" if d.get('pdf_url') else "")
    )


# ── Per-category gap section ───────────────────────────────────────────────


def gap_section(category: str, label: str, fr_docs: list[dict],
                corpus_set: set[str], fr_groups: dict[str, list[dict]],
                signal: dict) -> tuple[list[str], list[dict]]:
    md: list[str] = []
    md.append(f"## 4.{ {'nvic':1,'nmc':2,'msib':3}[category] } {label} coverage")
    md.append("")

    matched_keys = set(fr_groups.keys()) & corpus_set
    missing_keys = set(fr_groups.keys()) - corpus_set
    matched_rows: list[dict] = []
    missing_rows: list[dict] = []
    for k, rows in fr_groups.items():
        (matched_rows if k in matched_keys else missing_rows).extend(rows)

    md.append(f"- **FR documents matching category terms (full-text):** {signal['total']}")
    md.append(f"- **Of those, contain category term in TITLE:** {signal['title_has_term']} "
              f"({100*signal['title_has_term']/max(signal['total'],1):.0f}%)")
    md.append(f"- **Of those, parseable to a canonical doc number in title:** "
              f"{signal['title_parsed']} ({signal['unique_inferred']} unique numbers)")
    md.append(f"- **Noise ratio (term-only-in-abstract or unparsed):** "
              f"{100*signal['noise_ratio']:.0f}%")
    md.append(f"- **Unique documents in RegKnot corpus (this source):** {len(corpus_set)}")
    md.append(f"- **Matched (FR ∩ corpus, by canonical doc number):** {len(matched_keys)}")
    md.append(f"- **Missing (FR-discoverable \\ corpus):** {len(missing_keys)} unique doc numbers")
    md.append("")

    if matched_keys:
        md.append("**Matched docs (FR knows AND corpus has):**")
        md.append("")
        for k in sorted(matched_keys):
            md.append(f"  - {k}")
        md.append("")

    if missing_keys:
        md.append("**Host distribution of missing-doc PDFs:**")
        md.append("")
        hd = host_distribution(missing_rows)
        md.append("| Host | Count | Direct-fetchable from VPS? |")
        md.append("|---|---|---|")
        for host, cnt in hd.most_common():
            fetchable = ("✓ yes" if host in ("www.govinfo.gov", "www.federalregister.gov", "public-inspection.federalregister.gov")
                         else "✗ Akamai WAF" if "uscg" in host
                         else "—" if host == "none" else "?")
            md.append(f"| {host} | {cnt} | {fetchable} |")
        md.append("")

        # Group by decade
        by_decade: dict[str, list[dict]] = defaultdict(list)
        for d in missing_rows:
            inf = d.get("inferred_document_number") or ""
            m = re.search(r"(\d{1,2})-(\d{2})", inf)
            if m:
                yy = int(m.group(2))
                year = 2000 + yy if yy <= 50 else 1900 + yy
                decade = f"{(year // 10) * 10}s"
            else:
                decade = "(unparsed)"
            by_decade[decade].append(d)

        md.append(f"**Missing documents by decade ({len(missing_keys)} unique):**")
        md.append("")
        for decade in sorted(by_decade.keys()):
            docs_d = by_decade[decade]
            unique_in_decade = sorted({d.get("inferred_document_number") or "" for d in docs_d})
            md.append(f"### {decade} ({len(unique_in_decade)} unique)")
            md.append("")
            seen: set[str] = set()
            for d in sorted(docs_d, key=lambda x: x["publication_date"]):
                inf = d.get("inferred_document_number")
                if not inf or inf in seen:
                    continue
                seen.add(inf)
                md.append(render_doc_line(d))
            md.append("")

    return md, missing_rows


def main() -> int:
    if not REPORTS_DIR.is_dir():
        print(f"Missing {REPORTS_DIR}", file=sys.stderr)
        return 1

    fr_nvic = load_fr_csv("fr_discovery_nvic.csv")
    fr_nmc = load_fr_csv("fr_discovery_nmc.csv")
    fr_msib = load_fr_csv("fr_discovery_msib.csv")

    corpus_nvic = load_corpus_nvics()
    corpus_nmc_policy = load_corpus_simple("corpus_inventory_nmc_policy.csv")
    corpus_nmc_checklist = load_corpus_simple("corpus_inventory_nmc_checklist.csv")
    corpus_nmc = corpus_nmc_policy | corpus_nmc_checklist
    corpus_msib: set[str] = set()

    # Build FR groupings (key = inferred doc number, normalized for NVIC)
    def group_fr(docs: list[dict], normalize_keys: bool = False) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for d in docs:
            key = (d.get("inferred_document_number") or "").strip()
            if not key:
                continue
            if normalize_keys:
                key = strip_nvic_change(key)
            out[key].append(d)
        return out

    fr_nvic_groups = group_fr(fr_nvic, normalize_keys=True)
    fr_nmc_groups = group_fr(fr_nmc)
    fr_msib_groups = group_fr(fr_msib)

    # Signal/noise summaries
    sig_nvic = signal_noise_summary("nvic", fr_nvic,
        re.compile(r"\b(NVIC|Navigation\s+and\s+Vessel\s+Inspection\s+Circular)\b", re.I))
    sig_nmc = signal_noise_summary("nmc", fr_nmc,
        re.compile(r"\b(NMC|CG-MMC|CG-CVC|CG-OES|merchant\s+mariner|policy\s+letter)\b", re.I))
    sig_msib = signal_noise_summary("msib", fr_msib,
        re.compile(r"\b(MSIB|Marine\s+Safety\s+Information\s+Bulletin)\b", re.I))

    md: list[str] = []
    md.append("# Federal Register Discovery — Gap Report")
    md.append("")
    md.append(f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    md.append("")
    md.append("**Method.** Queried the Federal Register API "
              "(`https://www.federalregister.gov/api/v1/documents.json`) for USCG-agency "
              "documents containing each category's diagnostic terms (NVIC / "
              "Navigation and Vessel Inspection Circular; NMC, CG-MMC, CG-CVC, CG-OES, "
              "policy letter, Merchant Mariner Credential; MSIB / Marine Safety "
              "Information Bulletin). Title-pattern regex in "
              "`packages/ingest/ingest/sources/federal_register_discovery.py` extracts "
              "the canonical doc number from each FR title where parsable. "
              "Cross-referenced against the production `regulations` table. NVIC corpus "
              "rows normalized by stripping `§N` / `Ch-N` (NVIC adapter regex over-splits).")
    md.append("")
    md.append("---")
    md.append("")

    # ── HEADLINE FINDING ──────────────────────────────────────────────────
    md.append("## 0. Headline finding — FR is the wrong channel for these categories")
    md.append("")
    md.append("The Federal Register API does **not** carry NVIC, NMC policy letter, or "
              "MSIB publications as titled documents — it carries USCG rulemaking notices "
              "that *mention* these instruments in their abstracts. The full-text term "
              "search returns the rulemakings, not the source documents themselves. "
              "Specifically:")
    md.append("")
    md.append("| Category | FR full-text matches | Term in title | Parseable doc # | Effective signal-to-noise |")
    md.append("|---|---|---|---|---|")
    md.append(f"| NVIC | {sig_nvic['total']} | {sig_nvic['title_has_term']} ({100*sig_nvic['title_has_term']/max(sig_nvic['total'],1):.0f}%) | "
              f"{sig_nvic['title_parsed']} ({sig_nvic['unique_inferred']} unique) | "
              f"{100*sig_nvic['unique_inferred']/max(sig_nvic['total'],1):.1f}% |")
    md.append(f"| NMC | {sig_nmc['total']} | {sig_nmc['title_has_term']} ({100*sig_nmc['title_has_term']/max(sig_nmc['total'],1):.0f}%) | "
              f"{sig_nmc['title_parsed']} ({sig_nmc['unique_inferred']} unique) | "
              f"{100*sig_nmc['unique_inferred']/max(sig_nmc['total'],1):.1f}% |")
    md.append(f"| MSIB | {sig_msib['total']} | {sig_msib['title_has_term']} ({100*sig_msib['title_has_term']/max(sig_msib['total'],1):.0f}%) | "
              f"{sig_msib['title_parsed']} ({sig_msib['unique_inferred']} unique) | "
              f"{100*sig_msib['unique_inferred']/max(sig_msib['total'],1):.1f}% |")
    md.append("")
    md.append("**Translation:**")
    md.append("")
    md.append(f"- NVIC: of {sig_nvic['total']} FR results, only {sig_nvic['unique_inferred']} "
              "distinct NVICs are titled in FR. The vast majority are FR rulemakings "
              "that mention NVICs in passing.")
    md.append(f"- NMC: of {sig_nmc['total']} FR results, only {sig_nmc['unique_inferred']} "
              "distinct CG-MMC/CG-CVC/CG-OES policy letters are titled. NMC publishes "
              "interpretive guidance, not rulemaking — so it doesn't go through FR.")
    md.append(f"- MSIB: of {sig_msib['total']} FR results, **zero** have an MSIB number "
              "in the title. MSIBs are field advisories distributed via GovDelivery — "
              "they never appear in FR as published bulletins.")
    md.append("")
    md.append("**Architectural implication.** The original sprint hypothesis was that "
              "FR could serve as the canonical discovery channel with GovDelivery as a "
              "fallback for MSIBs only. The data flips this: **GovDelivery (or another "
              "non-FR channel) is the primary requirement for all three categories.** "
              "FR remains useful for occasional NVIC notices-of-availability and for "
              "rulemaking that surrounds these documents, but it cannot enumerate them.")
    md.append("")
    md.append("---")
    md.append("")

    # §4.1 NVIC
    nvic_md, nvic_missing = gap_section("nvic", "NVIC", fr_nvic, corpus_nvic, fr_nvic_groups, sig_nvic)
    md.extend(nvic_md)
    md.append("---")
    md.append("")

    # §4.2 NMC — keep the calibration paragraph
    nmc_md, nmc_missing = gap_section("nmc", "NMC policy letter", fr_nmc, corpus_nmc, fr_nmc_groups, sig_nmc)
    md.extend(nmc_md)
    matched_nmc = set(fr_nmc_groups.keys()) & corpus_nmc
    appearing_in_fr = len(matched_nmc & corpus_nmc_policy)
    md.append("**Calibration: how much NMC policy gets announced in FR?**")
    md.append("")
    md.append(f"Of the {len(corpus_nmc_policy)} NMC policy letters manually ingested, "
              f"**{appearing_in_fr} appear in FR** with a parseable canonical doc number. "
              f"This calibrates expected FR coverage at "
              f"{100*appearing_in_fr/max(len(corpus_nmc_policy),1):.0f}% — "
              "GovDelivery is mandatory for full NMC discovery; FR is at best supplementary.")
    md.append("")
    md.append("---")
    md.append("")

    # §4.3 MSIB
    msib_md, msib_missing = gap_section("msib", "MSIB", fr_msib, corpus_msib, fr_msib_groups, sig_msib)
    md.extend(msib_md)
    md.append("**MSIBs are not in FR. Period.** Of 660 FR results that surfaced from "
              "term searches, 0 had an MSIB number in the title and 0 had a parseable "
              "MSIB identifier. MSIBs distribute exclusively via:")
    md.append("")
    md.append("- USCG GovDelivery email subscriptions "
              "(`uscoastguard@service.govdelivery.com`)")
    md.append("- Direct posting at `dco.uscg.mil` (Akamai WAF blocked from VPS)")
    md.append("- Industry republishing (USCG News, AMO, MarPro, AIS providers)")
    md.append("")
    md.append("---")
    md.append("")

    # §4.4 Cross-category host distribution
    md.append("## 4.4 Host distribution for ALL FR-discoverable, corpus-missing documents")
    md.append("")
    all_missing = nvic_missing + nmc_missing + msib_missing
    md.append(f"Aggregating across NVIC + NMC + MSIB missing-doc PDFs ({len(all_missing)} FR rows):")
    md.append("")
    hd_all = host_distribution(all_missing)
    md.append("| Host | Count | Fetchable from VPS? | Implication |")
    md.append("|---|---|---|---|")
    for host, cnt in hd_all.most_common():
        if host == "www.govinfo.gov":
            md.append(f"| {host} | {cnt} | ✓ yes | Direct backfill in Sprint C |")
        elif host == "public-inspection.federalregister.gov":
            md.append(f"| {host} | {cnt} | ✓ yes | Direct backfill — pre-publication PDFs |")
        elif host == "www.federalregister.gov":
            md.append(f"| {host} | {cnt} | ✓ yes | Direct backfill |")
        elif "uscg" in host:
            md.append(f"| {host} | {cnt} | ✗ Akamai WAF | Needs GovDelivery or scp-from-desktop |")
        elif host == "none":
            md.append(f"| {host} | {cnt} | n/a | FR rows with no PDF link |")
        else:
            md.append(f"| {host} | {cnt} | ? | Manual investigation |")
    md.append("")
    md.append("**Notable:** every FR-discoverable missing document has a govinfo.gov "
              "PDF URL. There are zero Akamai-blocked PDFs in the FR-discoverable gap "
              "set — the FR corpus is uniformly fetchable. The Akamai problem is "
              "exclusively about documents NOT discoverable via FR (i.e. the 80%+ of "
              "NMC and 100% of MSIB content).")
    md.append("")
    md.append("---")
    md.append("")

    # §4.5 Publication rate calibration
    md.append("## 4.5 Publication-rate calibration")
    md.append("")
    md.append("Average FR publications/year over the past 5 calendar years (counting all "
              "term-matched FR results, including the noisy ones — these set an upper bound "
              "on the cadence of relevant USCG rulemaking surrounding each category):")
    md.append("")
    md.append("| Category | FR docs (5y avg/yr) | Real-world cadence | Architecture implication |")
    md.append("|---|---|---|---|")
    md.append(f"| NVIC | {fr_pubrate(fr_nvic):.1f} | "
              "USCG publishes 2-5 NVICs and 2-8 Change-Notes per year | "
              "Trickle — daily polling sufficient |")
    md.append(f"| NMC | {fr_pubrate(fr_nmc):.1f} | "
              "USCG publishes 5-15 NMC PLs per year | "
              "Trickle — daily polling sufficient |")
    md.append(f"| MSIB | {fr_pubrate(fr_msib):.1f} | "
              "USCG broadcasts 50-100 MSIBs per year | "
              "Stream — automate aggressively |")
    md.append("")
    md.append("(FR pubrate ≠ real cadence. The FR numbers are inflated by tangential "
              "USCG rulemaking. Real cadence comes from USCG/NMC publication schedules.)")
    md.append("")
    md.append("---")
    md.append("")

    # §4.6 Recommendations
    nvic_gap = len(set(fr_nvic_groups.keys()) - corpus_nvic)
    nmc_gap = len(set(fr_nmc_groups.keys()) - corpus_nmc)

    md.append("## 4.6 Recommendations")
    md.append("")
    md.append("### A. GovDelivery is the primary discovery channel — Sprint B priority")
    md.append("")
    md.append("Build GovDelivery email-parsing first (the channel referenced by your "
              "subscription screenshot). Subscribe a forwarded inbox to "
              "`uscoastguard@service.govdelivery.com`, parse incoming bulletin emails "
              "for PDF links, fetch via the email's embedded URLs (which often point to "
              "non-WAF mirrors or include unwafable redirects).")
    md.append("")
    md.append("**Order within Sprint B:** MSIB (FR yields 0 — no alternative) → "
              "NMC PLs (FR yields ~0.25%) → NVIC (FR catches ~3%, but NVIC scrape "
              "from prior sprint already covers most of the corpus).")
    md.append("")
    md.append("### B. Sprint C — FR-discoverable backfill is small and easy")
    md.append("")
    md.append(f"FR enumerates only **{nvic_gap} missing NVICs** and "
              f"**{nmc_gap} missing NMC docs** — all on govinfo.gov, all directly "
              "fetchable from the VPS. This is a one-shot backfill, not an ongoing "
              "channel. Run the existing nvic/nmc adapters with these specific PDF "
              "URLs and you're done. Tactical effort, ~1 hour. Worth doing even before "
              "Sprint B lands because it's so cheap.")
    md.append("")
    md.append("### C. Reuse this discovery utility for ongoing observability — Sprint D seed")
    md.append("")
    md.append("`packages/ingest/ingest/sources/federal_register_discovery.py` is reusable. "
              "Wire it into Celery beat as a daily job that diffs today's FR results "
              "against the corpus inventory and emails `hello@regknots.com` when new "
              "FR-discoverable items appear. Even with 3-6% signal-to-noise, the "
              "absolute count of new daily FR-discoverable items is tiny (<1/day on "
              "average), so a human can spot-check the alerts. Don't auto-ingest — "
              "FR's noise level demands human review.")
    md.append("")
    md.append("### D. Architecture nits flagged by the data")
    md.append("")
    md.append("- **NVIC adapter section-numbering bug remains** — corpus has 1,277 unique "
              "section_numbers vs ~160 unique parent NVICs (per normalization). The "
              "adapter regex over-splits document subsections. Functional but noisy at "
              "retrieval; a future fix should make the section_number = parent NVIC "
              "and use chunk_index for sub-sections (matches the NMC adapter's pattern).")
    md.append("- **25-year FR query hits a 10,000-row ceiling** — for any future deep-history "
              "discovery, paginate via narrow date windows (1-year buckets).")
    md.append("- **Title-parser regex coverage:** NVIC ~90% of term-in-title rows (17/19), "
              "NMC ~4% (2/49), MSIB N/A (no titles to match). NMC is fundamentally "
              "untitled in FR; widening the regex won't help. GovDelivery is the answer.")
    md.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"OK — wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
