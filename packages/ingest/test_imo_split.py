"""2026-10-08 — the IMO splitters keep every character (preamble, short chapters)."""
from datetime import date

from ingest.sources import imo_codes as M

META = M.CodeDocMeta(code="MSC.572(110)", title="Amendments to SOLAS chapters II-2 and V",
                     pdf_url="https://example/MSC.572(110).pdf", effective_date=date(2028, 1, 1),
                     parent_label="IMO MSC Resolution")

PREAMBLE = ("RESOLUTION MSC.572(110) (adopted on 26 June 2025)\n"
            "THE MARITIME SAFETY COMMITTEE, RECALLING Article 28(b) of the Convention...\n"
            "2 DETERMINES that the amendments shall be deemed to have been accepted on 1 July 2027\n"
            "3 INVITES Contracting Governments to note that the amendments shall enter into force on "
            "1 January 2028.\n" + "Regulation 23 Pilot transfer arrangements is replaced by the following text. " * 8)
CH17 = "\n".join(f"17.{i} Pilot ladder item {i} with enough words to count as a paragraph of the record" for i in range(1, 9))
CH18_SHORT = "18.1 Short heading\n18.2 Tiny"
CH19 = "\n".join(f"19.{i} Another numbered paragraph describing equipment and records in detail" for i in range(1, 9))
TEXT = PREAMBLE + "\n" + CH17 + "\n" + CH18_SHORT + "\n" + CH19


def test_paragraph_split_keeps_preamble_and_short_chapters():
    secs = M._split_by_paragraph_chapter(TEXT, META, "imo_msc")
    names = [s.section_number for s in secs]
    assert names[0] == "IMO MSC Resolution MSC.572(110)"          # the preamble, named for the resolution
    assert "enter into force on 1 January 2028" in secs[0].full_text
    assert "IMO MSC Resolution MSC.572(110) Ch.17" in names
    assert "IMO MSC Resolution MSC.572(110) Ch.18" not in names   # too short: merged, not dropped
    kept = "".join(s.full_text for s in secs)
    assert "18.2 Tiny" in kept and "Regulation 23 Pilot transfer" in kept
    assert len(kept.replace("\n", "")) >= 0.98 * len(TEXT.replace("\n", ""))


def test_chapter_split_keeps_the_preamble():
    text = ("RESOLUTION MSC.98(73) adopted ... the Code shall enter into force on 1 July 2002. " * 5 +
            "\nCHAPTER 1 — GENERAL\n" + "General text. " * 40 +
            "\nCHAPTER 2 — INTERNATIONAL SHORE CONNECTIONS\n" + "Shore connection text. " * 40)
    meta = M.CodeDocMeta(code="MSC.98(73)", title="FSS Code", pdf_url="https://example/x.pdf",
                         effective_date=date(2002, 7, 1), parent_label="IMO FSS Code")
    secs = M._split_into_chapters(text, meta, "imo_fss")
    assert [s.section_number for s in secs] == ["IMO FSS Code MSC.98(73)", "IMO FSS Code MSC.98(73) Ch.1",
                                                "IMO FSS Code MSC.98(73) Ch.2"]
    assert "enter into force on 1 July 2002" in secs[0].full_text
