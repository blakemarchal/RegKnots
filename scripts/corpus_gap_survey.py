"""Corpus gap survey — find Parts/chapters with sparse coverage.

Run on the VPS:
    cd /opt/RegKnots/apps/api
    /root/.local/bin/uv run python /opt/RegKnots/scripts/corpus_gap_survey.py

Three passes:
  1. CFR Part-level coverage (cfr_33, cfr_46, cfr_49).
  2. IMO Code chapter-level coverage (solas, marpol, stcw, igc, ibc, hsc, fss, lsa, imdg, colregs).
  3. NVIC inventory.

Output: stdout, sorted by gap severity. The intent is to surface
'this Part has 3 sections; the official CFR has 50' — not to do the
canonical eCFR comparison, just to give a triage list.

For each CFR Part we emit (source, part, distinct_sections,
sample_section_numbers) so a human reviewer can spot-check whether
the coverage is intentionally narrow (procedural/admin Parts that
genuinely only have a few sections) or genuinely sparse (substantive
Parts that should have many).
"""
import re
import asyncpg
import asyncio
import os


async def main():
    # Run inside apps/api so it picks up DATABASE_URL from env
    db_url = os.environ.get("REGKNOTS_DATABASE_URL", "")
    if not db_url:
        # Fall back: read from .env directly
        with open("/opt/RegKnots/.env") as f:
            for line in f:
                if line.startswith("REGKNOTS_DATABASE_URL="):
                    db_url = line.split("=", 1)[1].strip()
                    break
    if "postgresql+asyncpg://" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(db_url)

    print("=" * 78)
    print("CFR — Part-level coverage")
    print("=" * 78)
    print()

    # CFR: extract leading "<title> CFR <part>" prefix, group by Part.
    cfr_part_re = re.compile(r"^(\d+ CFR \d+)")
    rows = await conn.fetch(
        """
        SELECT source, section_number
        FROM regulations
        WHERE source IN ('cfr_33', 'cfr_46', 'cfr_49')
          AND section_number IS NOT NULL
        """
    )
    cfr: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        m = cfr_part_re.match(r["section_number"])
        if m:
            key = (r["source"], m.group(1))
            cfr.setdefault(key, set()).add(r["section_number"])

    # Sort by source then by Part number numerically
    def part_key(item):
        (source, part), _ = item
        m = re.match(r"\d+ CFR (\d+)", part)
        return (source, int(m.group(1)) if m else 9999)

    print(f"{'Source':<8} {'Part':<18} {'Distinct sections':>17}")
    print("-" * 50)
    for (source, part), sections in sorted(cfr.items(), key=part_key):
        print(f"{source:<8} {part:<18} {len(sections):>17}")

    print()
    print("=" * 78)
    print("CFR — Parts with FEW distinct sections (≤3) — likely gap candidates")
    print("=" * 78)
    print()
    print(f"{'Source':<8} {'Part':<18} {'Sections':>9}  Sample")
    print("-" * 78)
    for (source, part), sections in sorted(cfr.items(), key=part_key):
        if len(sections) <= 3:
            sample = ", ".join(sorted(sections)[:3])
            print(f"{source:<8} {part:<18} {len(sections):>9}  {sample}")

    print()
    print("=" * 78)
    print("IMO Code coverage by source")
    print("=" * 78)
    print()
    for source in [
        "solas", "marpol", "stcw", "imdg", "colregs", "ism", "ism_supplement",
        "imo_igc", "imo_hsc", "imo_ibc", "fss", "lsa",
        "load_lines", "polar_code", "bwm",
    ]:
        rows = await conn.fetch(
            """
            SELECT
              COUNT(DISTINCT section_number) AS sections,
              COUNT(*) AS chunks,
              MIN(updated_at) AS oldest,
              MAX(updated_at) AS newest
            FROM regulations
            WHERE source = $1
            """,
            source,
        )
        if rows[0]["chunks"] == 0:
            print(f"  {source:<22} (no rows — source not ingested)")
        else:
            print(
                f"  {source:<22} sections={rows[0]['sections']:>5}  "
                f"chunks={rows[0]['chunks']:>5}  "
                f"latest={rows[0]['newest'].date() if rows[0]['newest'] else 'unknown'}"
            )

    print()
    print("=" * 78)
    print("NVIC inventory")
    print("=" * 78)
    print()
    rows = await conn.fetch(
        """
        SELECT DISTINCT REGEXP_REPLACE(section_number, '^(NVIC \d+-\d+).*', '\\1') AS nvic_id
        FROM regulations
        WHERE source = 'nvic'
        ORDER BY 1
        """
    )
    nvic_ids = sorted({r["nvic_id"] for r in rows if r["nvic_id"]})
    print(f"  Total distinct NVICs: {len(nvic_ids)}")
    print()
    # Group by year
    by_year: dict[str, list[str]] = {}
    for nid in nvic_ids:
        m = re.match(r"NVIC (\d{2})-(\d{2})", nid)
        if m:
            yy = m.group(2)
            year = f"20{yy}" if int(yy) < 50 else f"19{yy}"
            by_year.setdefault(year, []).append(nid)
    for year in sorted(by_year):
        print(f"  {year}: {', '.join(sorted(by_year[year]))}")

    print()
    print("=" * 78)
    print("USCG MSM chapter coverage")
    print("=" * 78)
    rows = await conn.fetch(
        """
        SELECT DISTINCT REGEXP_REPLACE(section_number, '(USCG MSM \\S+\\.\\d+)( Ch\\.\\d+)?.*', '\\1\\2') AS chapter,
               COUNT(*) AS chunks
        FROM regulations
        WHERE source = 'uscg_msm'
        GROUP BY 1
        ORDER BY 1
        """
    )
    for r in rows:
        print(f"  {r['chapter']:<40} chunks={r['chunks']}")

    print()
    print("=" * 78)
    print("Sources with very few chunks (might be partial ingests)")
    print("=" * 78)
    rows = await conn.fetch(
        """
        SELECT source, COUNT(*) AS chunks
        FROM regulations
        GROUP BY source
        HAVING COUNT(*) < 50
        ORDER BY chunks
        """
    )
    for r in rows:
        print(f"  {r['source']:<22} chunks={r['chunks']:>4}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
