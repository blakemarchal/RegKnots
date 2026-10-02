"""2026-10-02 — NGA navigation manuals: Bowditch articles, Pub 1310 headings,
Pub 102 sections."""
from ingest.sources import nga_pubs as n
from ingest.sources.uscg_docs import Doc

BOWDITCH = Doc(doc_id="Bowditch Vol. I", title="Bowditch", url="u", filename="2_Bowditch_Vol_1_LoRes.pdf",
               published="2024-05-17")
P1310 = Doc(doc_id="Pub 1310 Ch.3", title="Collision Avoidance", url="u", filename="10_310ch3.pdf",
            published="2019-09-20")
P102 = Doc(doc_id="Pub 102 Ch.4", title="Distress and Lifesaving Signals", url="u", filename="7_Chapter4.pdf",
           published="2020-10-30")

TEXT = "Plain sailing text that runs long enough to count as an article body, about the method. " * 3


def test_bowditch_articles_belong_to_their_chapter_and_skip_the_toc_and_appendices():
    text = "\n".join([
        "CHAPTER 13. THE SAILINGS ........ 227",             # contents page: not a heading
        "CHAPTER 13", "", "THE SAILINGS", "", "INTRODUCTION",
        "1300. Introduction", TEXT,
        "THE SAILINGS",                                       # running head
        "1301. Kinds of Sailings", TEXT,
        "2405. A stray number from another chapter", TEXT,    # not Ch.13 or Ch.14: body text
        "1302. References", TEXT,                             # reference lists are left out
        "CHAPTER 42 WEATHER ROUTING", "4200. Introduction", TEXT,
        "APPENDICES", "4201. Not an article", TEXT,
    ])
    secs = n.bowditch_sections(BOWDITCH, text)
    assert [s.section_number for s in secs] == ["Bowditch Art.1300", "Bowditch Art.1301", "Bowditch Art.4200"]
    assert secs[1].section_title == "Bowditch Ch.13 The Sailings — 1301. Kinds of Sailings"
    assert secs[1].parent_section_number == "Bowditch Ch.13"
    assert "THE SAILINGS" not in secs[1].full_text and "stray number" in secs[1].full_text
    assert secs[2].section_title.startswith("Bowditch Ch.42 Weather Routing — 4200.")
    assert str(secs[0].up_to_date_as_of) == "2024-05-17"


def test_bowditch_heading_read_without_its_text_folds_into_the_next():
    text = "\n".join(["CHAPTER 4", "HYDROGRAPHY", "410. Introduction", "", "411. Zones of Confidence", TEXT])
    [sec] = n.bowditch_sections(BOWDITCH, text)
    assert sec.section_number == "Bowditch Art.410"
    assert sec.section_title == "Bowditch Ch.4 Hydrography — 410. Introduction; 411. Zones of Confidence"


def test_pub1310_splits_at_headings_not_figure_labels_and_merges_short_parts():
    long = "Relative motion is motion with respect to an arbitrarily selected object. " * 14
    text = "\n".join([
        "CHAPTER 3 — COLLISION AVOIDANCE",
        "RELATIVE MOTION", long,
        "NRML RML DRM", "M1 M2 M3",                            # figure labels
        "VECTOR EQUATIONS", "Short.",                          # too short alone: joins the next
        "CLOSEST POINT OF APPROACH", long,
    ])
    secs = n.pub1310_sections(P1310, text)
    assert [s.section_number for s in secs] == ["Pub 1310 Ch.3 Sec.1", "Pub 1310 Ch.3 Sec.2"]
    assert secs[0].section_title == "Pub 1310 Ch.3 Collision Avoidance — Relative Motion"
    assert secs[1].section_title.endswith("— Vector Equations; Closest Point of Approach")
    assert "NRML RML DRM" in secs[0].full_text


def test_pub102_sections_drop_contents_and_running_heads():
    text = "\n".join([
        "CHAPTER 4",
        "SECTION 1: DISTRESS SIGNALS . . . . . . . . . . . . 147",
        "SECTION 1: DISTRESS SIGNALS",
        "1. A gun or other explosive signal fired at intervals of about a minute.",
        "SECTION 1.—DISTRESS SIGNALS Meaning", "Code",
        "2. A continuous sounding with any fog-signaling apparatus.",
        "SECTION 2: TABLE OF LIFESAVING SIGNALS",
        "Landing signals for the guidance of small boats . . . . . . . . . . K",
    ])
    secs = n.pub102_sections(P102, text)
    assert [s.section_number for s in secs] == ["Pub 102 Ch.4 Sec.1", "Pub 102 Ch.4 Sec.2"]
    assert secs[0].section_title.endswith("— Section 1: Distress Signals")
    assert "Meaning" not in secs[0].full_text and "fog-signaling" in secs[0].full_text
    assert secs[1].full_text.endswith("small boats … K")


def test_discover_takes_current_keys_from_the_listing():
    docs = n.discover({(10, "310ch3.pdf"): ("99999/SFH00000/310ch3.pdf", "2026-01-02")})
    ch3 = next(d for d in docs if d.doc_id == "Pub 1310 Ch.3")
    assert ch3.url.endswith("key=99999/SFH00000/310ch3.pdf&type=view") and ch3.published == "2026-01-02"
    bowditch = next(d for d in docs if d.doc_id == "Bowditch Vol. I")
    assert bowditch.url.endswith("key=16693975/SFH00000/Bowditch_Vol_1_LoRes.pdf&type=view")
    assert len({d.filename for d in docs}) == len(docs)


def test_title_case_keeps_acronyms_and_small_words():
    assert n.title_case("AUTOMATIC RADAR PLOTTING AIDS (ARPA)") == "Automatic Radar Plotting Aids (ARPA)"
    assert n.title_case("SHORT RANGE AIDS TO NAVIGATION") == "Short Range Aids to Navigation"
    assert n.normalize("course 000˚, radiotele-\nphony") == "course 000°, radiotelephony"
