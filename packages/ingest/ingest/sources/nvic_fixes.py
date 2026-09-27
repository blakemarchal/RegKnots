"""
Corrections to the text layer of USCG NVIC PDFs (2026-09-27).

Some older NVICs on dco.uscg.mil are retyped from scans of the originals, and
the retyping kept the scanner's misreads. NVIC 6-72 prints "discharge of 35%
of the required quantity of CO2 ... within two minutes" where 46 CFR 34.15-5,
76.15-5 and 95.15-5 require at least 85 percent; it prints "213" for 2/3 and
"S/S" for 5/8, and every temperature lost its degree sign to a trailing 0
("l300F" is 130°F). pdfplumber also runs superscript footnote numbers into the
figure before them ("3" + footnote 13 reads "313 parts").

The PDFs stay as published. nvic._parse_nvic_pdf applies these fixes to the
extracted text before the section split, so every re-ingest (including the
weekly --update) keeps them.

Each fix is (old, new). `old` must occur exactly once in the NVIC's extracted
lines joined with "\\n"; otherwise it is logged and skipped (USCG may
re-publish a corrected PDF). A fix only changes a figure when the right value
is fixed by the document itself (a restatement, its own arithmetic) or by the
CFR section it cites. Where the PDF prints a plausible wrong figure, the fix
carries a bracketed note so a reader comparing against the PDF sees why.
"""

import logging

logger = logging.getLogger(__name__)

NVIC_TEXT_FIXES: dict[str, list[tuple[str, str]]] = {
    # Guide to Fixed Fire-Fighting Equipment Aboard Merchant Vessels (1972,
    # Change 1). Checked against the rendered pages and the guide's own
    # arithmetic. Left as printed (not provable from the document): the water
    # spray "Contracted for" dates (1 January 1964, 19 November 1962), "69.9%"
    # of pipe area (its arithmetic gives 69.4%), "R = 300ft2" in the fixed foam
    # example (the text says 3000 ft2), and misread CFR citations ("95.15-S").
    "06-72": [
        # ── I. Fire main ──
        # A.2.2 and B.3: 2/3 of the bilge pump capacity, as A.2.2(1) and Example I restate it.
        ("213 of the required bilge pump capacity.", "2/3 of the required bilge pump capacity."),
        ("total capacity must equal 213 of", "total capacity must equal 2/3 of"),
        # A.2.2(3): 75 psi for tankers (C.1.1).
        ("(7S psi Pitot pressure for tankers)", "(75 psi Pitot pressure for tankers)"),
        # A.6: 125 psi + footnote 6 (B.7: "relieve at either 125 psi").
        ("operate at l256 psi or 25 psi", "operate at 125 psi or 25 psi"),
        ("The required SO", "The required 50"),
        # A.7.1: the 1 1/2" hydrant nozzle is 5/8" (K = 11.70 above).
        ('hydrant with S/S" nozzle', 'hydrant with 5/8" nozzle'),
        ("reach temperatures of 20000F", "reach temperatures of 2000°F"),
        # ── II. Carbon dioxide ──
        # A.2.3: the guide's own B.11 has the required amount discharged within 2 minutes.
        ("discharge of 35% of the required quantity",
         'discharge of 85% [corrected: the USCG PDF reads "35%"; 46 CFR 34.15-5, 76.15-5 '
         'and 95.15-5 require at least 85 percent within 2 minutes] of the required quantity'),
        # A.3: "no reduction in volume is allowed", read as "110".
        ("However, i~ computing the volume of the space protected 110",
         "However, in computing the volume of the space protected no"),
        ("to reduce the oxygen content to l5'~.", "to reduce the oxygen content to 15%."),
        ("(this is at 860F)", "(this is at 86°F)"),
        # A.8.1: -180 + 460 = 280 and 150 + 460 = 610 fix both temperatures.
        ("T = - 1800F + 460= 2800R", "T = -180°F + 460 = 280°R"),
        ("be 1500F. (6l00R).", "be 150°F (610°R)."),
        ("1300F. This is to prevent", "130°F. This is to prevent"),
        ("in excess of l300F.(.15-20(c))", "in excess of 130°F (.15-20(c))"),
        # ── III. Foam ──
        # A.3.1: superscript footnote 13 and a stray superscript 1 (3 + 97, 6 + 94).
        ("313 parts concentrate, 97 parts water", "3 parts concentrate, 97 parts water"),
        ("61 parts concentrate, 94 parts water", "6 parts concentrate, 94 parts water"),
        # A.3.1: the deck foam rate on total tank area is 0.016 throughout the paragraph.
        ("Again, using the 0.16 gpm/ft2 of total",
         'Again, using the 0.016 gpm/ft2 [corrected: the USCG PDF reads "0.16"; the deck '
         'foam rate on total tank area is 0.016 gpm/ft2, as stated above] of total'),
        ("(3~ or 6~)", "(3% or 6%)"),
        # ── IV. Water spray ──
        ("a temperature of 20000F was reached", "a temperature of 2000°F was reached"),
        ("up to 2000-22000 F until", "up to 2000-2200°F until"),
        # ── V. Manual sprinkling ──
        ("(above 2000F) combustible liquids", "(above 200°F) combustible liquids"),
        # A.3.1: B.13 and C.1.5 require 3/8" heads, and K = 3.15 (3/8") gives 12.2 gpm at 15 psi.
        ('the 5/8" diameter sprinkler will deliver l2 gpm, meeting the 12 gpm/l00',
         'the 3/8" [corrected: the USCG PDF reads 5/8 inch; this guide requires 3/8-inch '
         'sprinklers, and a 3/8-inch sprinkler delivers 12.2 gpm at 15 psi] diameter sprinkler '
         'will deliver 12 gpm, meeting the 12 gpm/100'),
        # ── VI. Halon 1301 ── (900°F = 482°C; the flooding factors match s at 0°F and 32°F)
        ("above 9000F (4820C)", "above 900°F (482°C)"),
        ("usually greater than 700F", "usually greater than 70°F"),
        (".0289 lb/ft3 (00F)", ".0289 lb/ft3 (0°F)"),
        (".0270 lb/ft3 (320F)", ".0270 lb/ft3 (32°F)"),
        ("T = Design Temperature, 0F", "T = Design Temperature, °F"),
        ("(at 700F): 360 or 600 psig", "(at 70°F): 360 or 600 psig"),
        ("between 1300F and -200F", "between 130°F and -20°F"),
        ("00F (Section B.3 for pump rooms)", "0°F (Section B.3 for pump rooms)"),
        ("At 00F., s = 2.2062", "At 0°F, s = 2.2062"),
        ("will not normally drop below 700F.", "will not normally drop below 70°F."),
        ("T = 700F", "T = 70°F"),
        ("temperature not to exceed 700F.", "temperature not to exceed 70°F."),
        ("between -200F and 1300F.", "between -20°F and 130°F."),
        # D.2: cylinder pressure by temperature (70°F = 360 / 600 psig, as in B.6).
        ("400F 275 psig 500 psig\n500F 300 psig 530 psig\n600F 330 psig 565 psig\n"
         "700F 360 psig 600 psig\n800F 395 psig 640 psig\n900F 430 psig 680 psig\n"
         "1000F 470 psig 730 psig",
         "40°F 275 psig 500 psig\n50°F 300 psig 530 psig\n60°F 330 psig 565 psig\n"
         "70°F 360 psig 600 psig\n80°F 395 psig 640 psig\n90°F 430 psig 680 psig\n"
         "100°F 470 psig 730 psig"),
    ],
}


def apply_text_fixes(number: str, lines: list[str]) -> list[str]:
    """Apply NVIC_TEXT_FIXES[number] to one NVIC's extracted lines.

    The lines are joined with "\\n" so an anchor may span lines. An anchor that
    does not occur exactly once is logged and skipped.
    """
    fixes = NVIC_TEXT_FIXES.get(number)
    if not fixes:
        return lines
    text = "\n".join(lines)
    applied = 0
    for old, new in fixes:
        hits = text.count(old)
        if hits != 1:
            logger.warning("nvic: NVIC %s text fix %r: anchor found %d times; skipped",
                           number, old[:60], hits)
            continue
        text = text.replace(old, new)
        applied += 1
    logger.info("nvic: NVIC %s: %d of %d text fixes applied", number, applied, len(fixes))
    return text.split("\n")
