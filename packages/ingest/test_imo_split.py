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


# 2026-10-17 — the scanned LSA Code: "CHAPTERI-GENER~L", "CHAPTER 11" for II, and a
# contents line "CHAPTER 1II -VISUAL SIGNALS".
LSA_META = M.CodeDocMeta(code="MSC.48(66)", title="LSA Code", pdf_url="https://example/x.pdf",
                         effective_date=date(1998, 7, 1), parent_label="IMO LSA Code")


def test_chapter_split_reads_ocr_roman_numerals():
    toc = ("CHAPTER I -GENERAL\nCHAPTER II -PERSONAL LIFE-SAVING APPLIANCES\n"
           "CHAPTER 1II -VISUAL SIGNALS\nCHAPTER IV -SURVIVAL CRAFT\n")
    text = ("RESOLUTION MSC.48(66) (adopted on 4 June 1996) the Code shall be mandatory. " * 4 + "\n" + toc
            + "CHAPTERI-GENER~L\n" + "1.1 Definitions text. " * 30
            + "\nCHAPTER 11 -PERSONAL LIFE-SAVING APPLIANCES\n" + "2.1 Lifebuoys text. " * 30
            + "\nCHAPTER III -VISUAL SIGNALS\n" + "3.1 Rocket parachute flares. " * 30
            + "\nCHAPTER IV -SURVIVAL CRAFT\n" + "4.1 General requirements. " * 30)
    secs = M._split_into_chapters(text, LSA_META, "imo_lsa")
    names = [s.section_number.removeprefix("IMO LSA Code MSC.48(66)") for s in secs]
    assert names == ["", " Ch.I", " Ch.II", " Ch.III", " Ch.IV"]
    assert secs[1].section_title == "IMO LSA Code Chapter I — GENERAL"     # the contents' clean title
    assert secs[1].full_text.startswith("CHAPTERI-GENER~L\n1.1 Definitions")
    assert secs[2].full_text.startswith("CHAPTER 11 -PERSONAL")
    assert "CHAPTER 1II -VISUAL SIGNALS" in secs[0].full_text            # contents stay in the preamble


def test_arabic_chapter_numbers_stay_arabic():
    text = ("RESOLUTION MSC.98(73) ... " * 10 + "\nCHAPTER 1 — GENERAL\n" + "General text. " * 40
            + "\nCHAPTER 11 — FIXED FIRE DETECTION\n" + "Detection text. " * 40)
    secs = M._split_into_chapters(text, LSA_META, "imo_fss")
    assert [s.section_number.rsplit(" ", 1)[-1] for s in secs[1:]] == ["Ch.1", "Ch.11"]


# 2026-10-17 — MSC.81(70): PART 1 and PART 2 restart their numbering, and a contents
# list of every N.N heading comes first.
def test_paragraph_split_in_parts():
    meta = M.CodeDocMeta(code="MSC.81(70)", title="Testing of LSA", pdf_url="https://example/y.pdf",
                         effective_date=date(1998, 12, 11), parent_label="IMO LSA Code")
    contents = ("PART 1 - PROTOTYPE TESTS FOR LIFE-SAVING APPLIANCES\n1 LIFEBUOYS\n1.1 Lifebuoy specification\n"
                "1.2 Lifebuoy drop test\n2 LIFEJACKETS\n2.1 Temperature cycling test\n2.2 Buoyancy test\n"
                "PART 2 - PRODUCTION AND INSTALLATION TESTS\n1 GENERAL\n1.1 Scope\n1.2 Samples\n"
                "2 INDIVIDUAL BUOYANCY EQUIPMENT\n2.1 Lifejackets\n2.2 Lifebuoys\n")
    para = "with enough words in it to be a real paragraph of the recommendation. " * 6

    def section(n: int, title: str) -> str:
        return f"{n} {title}\n" + "".join(f"{n}.{i} Heading {i}\n{para}\n" for i in (1, 2, 3))

    body = ("PART 1 - PROTOTYPE TESTS FOR LIFE-SAVING APPLIANCES\n" + section(1, "LIFEBUOYS")
            + section(2, "LIFEJACKETS") + "PART 2 - PRODUCTION AND INSTALLATION TESTS\n"
            + section(1, "GENERAL") + section(2, "INDIVIDUAL BUOYANCY EQUIPMENT"))
    text = "RESOLUTION MSC.81(70) (adopted on 11 December 1998) " * 5 + "\n" + contents + body
    secs = M._split_by_paragraph_chapter(text, meta, "imo_lsa")
    names = [s.section_number.removeprefix("IMO LSA Code MSC.81(70)") for s in secs]
    assert names == ["", " Pt.1 Ch.1", " Pt.1 Ch.2", " Pt.2 Ch.1", " Pt.2 Ch.2"]
    assert "1.2 Lifebuoy drop test" in secs[0].full_text                  # the contents: preamble
    assert secs[1].full_text.startswith("PART 1 - PROTOTYPE TESTS")
    assert secs[2].section_title == "IMO LSA Code Part 1 Section 2 — LIFEJACKETS"
    assert secs[3].full_text.startswith("PART 2 - PRODUCTION AND INSTALLATION TESTS\n1 GENERAL")
    assert sum(len(s.full_text) for s in secs) >= 0.98 * len(text.strip())


def test_chapters_restarting_in_parts_are_labelled_by_part():
    # the 2008 IS Code: PART A chapters 1-3, PART B (OCR'd "PARTB") chapters 1-8,
    # Part B's first heading OCR'd "CHAPTERI"
    meta = M.CodeDocMeta(code="MSC.267(85)", title="2008 IS Code", pdf_url="https://example/is.pdf",
                         effective_date=date(2010, 7, 1), parent_label="IMO MSC Resolution")
    words = "Stability text for the chapter body. " * 12
    text = ("RESOLUTION MSC.267(85) (adopted on 4 December 2008) " * 5
            + "\nPART A - MANDATORY CRITERIA\nPART B - RECOMMENDATIONS\n"
            + "PART A\nMANDATORY CRITERIA\nCHAPTER 1 - GENERAL\n" + words
            + "\nCHAPTER 2 - GENERAL CRITERIA\n" + words
            + "\nPARTB\nRECOMMENDATIONS FOR CERTAIN TYPES OF SHIPS\nCHAPTERI - GENERAL\n" + words
            + "\nCHAPTER 2 - RECOMMENDED DESIGN CRITERIA\n" + words
            + "\nCHAPTER 3 - GUIDANCE IN PREPARING STABILITY INFORMATION\n" + words)
    secs = M._split_into_chapters(text, meta, "imo_msc")
    names = [s.section_number.removeprefix("IMO MSC Resolution MSC.267(85)") for s in secs]
    assert names == ["", " Pt.A Ch.1", " Pt.A Ch.2", " Pt.B Ch.1", " Pt.B Ch.2", " Pt.B Ch.3"]
    assert secs[2].section_title == "IMO MSC Resolution Part A Chapter 2 — GENERAL CRITERIA"
    assert secs[1].full_text.startswith("PART A\nMANDATORY CRITERIA\nCHAPTER 1")
    assert secs[3].full_text.startswith("PARTB\nRECOMMENDATIONS")
    assert "PART B - RECOMMENDATIONS" in secs[0].full_text                 # contents: preamble


def test_parts_that_do_not_restart_numbering_keep_the_plain_split():
    meta = M.CodeDocMeta(code="MEPC.107(49)", title="Bilge separators", pdf_url="https://example/z.pdf",
                         effective_date=date(2005, 1, 1), parent_label="IMO MEPC Resolution")
    para = "with enough words in it to be a real paragraph of the guidelines. " * 6
    body = ("PART 1 - GENERAL\n" + "".join(f"1.{i} Item\n{para}\n" for i in (1, 2, 3))
            + "".join(f"2.{i} Item\n{para}\n" for i in (1, 2, 3))
            + "PART 2 - TEST SPECIFICATIONS\n" + "".join(f"3.{i} Item\n{para}\n" for i in (1, 2, 3)))
    text = "RESOLUTION MEPC.107(49) adopted 18 July 2003 " * 5 + "\n" + body
    secs = M._split_by_paragraph_chapter(text, meta, "imo_mepc")
    assert [s.section_number.rsplit(" ", 1)[-1] for s in secs[1:]] == ["Ch.1", "Ch.2", "Ch.3"]
