"""Write user-supplied manual transcriptions for the 3 OCR-blocked MARPOL spreads.

Sprint D6.11 — Anthropic's output content filter persistently refused
three two-page spreads (book pages 15-16 Article 16 / 179-180 Annex II
Ch.3 surveys / 239-240 Annex IV Ch.2 surveys), even with split-fallback.
Blake transcribed them directly from the IMO e-Publications viewer.

This script writes those transcriptions to extracted/raw/<sha>.txt using
the SAME `=== Left/Right page (book p.N) ===` envelope Sonnet emits, and
flips the manifest entries from status='error' to status='ok' with
source='manual_transcription'. Downstream consolidation reads them
indistinguishably from auto-OCR'd content.

Idempotent — re-running just overwrites the same files.

Run on the VPS:

    /root/.local/bin/uv run --directory /opt/RegKnots/packages/ingest \\
        python /opt/RegKnots/scripts/manual_marpol_pages.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXTRACTED_DIR = Path("/opt/RegKnots/data/raw/marpol/extracted/raw")
MANIFEST_PATH = Path("/opt/RegKnots/data/raw/marpol/extracted/_manifest.json")
SOURCE_DIR = Path("/opt/RegKnots/data/raw/marpol")


# ── Gap 1 — pages 15-16: end of Article 15 + Article 16 (Amendments) ─────────

GAP1_LEFT = """\
(4) For States which have deposited an instrument of ratification, acceptance, approval or accession in respect of the present Convention or any Optional Annex after the requirements for entry into force thereof have been met but prior to the date of entry into force, the ratification, acceptance, approval or accession shall take effect on the date of entry into force of the Convention or such Annex or three months after the date of deposit of the instrument whichever is the later date.

(5) For States which have deposited an instrument of ratification, acceptance, approval or accession after the date on which the Convention or an Optional Annex entered into force, the Convention or the Optional Annex shall become effective three months after the date of deposit of the instrument.

(6) After the date on which all the conditions required under article 16 to bring an amendment to the present Convention or an Optional Annex into force have been fulfilled, any instrument of ratification, acceptance, approval or accession deposited shall apply to the Convention or Annex as amended."""

GAP1_RIGHT = """\
Article 16
Amendments

(1) The present Convention may be amended by any of the procedures specified in the following paragraphs.

(2) Amendments after consideration by the Organization:

(a)  any amendment proposed by a Party to the Convention shall be submitted to the Organization and circulated by its Secretary-General to all Members of the Organization and all Parties at least six months prior to its consideration;
(b)  any amendment proposed and circulated as above shall be submitted to an appropriate body by the Organization for consideration;
(c)  Parties to the Convention, whether or not Members of the Organization, shall be entitled to participate in the proceedings of the appropriate body;
(d)  amendments shall be adopted by a two-thirds majority of only the Parties to the Convention present and voting;
(e)  if adopted in accordance with subparagraph (d) above, amendments shall be communicated by the Secretary-General of the Organization to all the Parties to the Convention for acceptance;
(f)  an amendment shall be deemed to have been accepted in the following circumstances:
(i)  an amendment to an article of the Convention shall be deemed to have been accepted on the date on which it is accepted by two thirds of the Parties, the combined merchant fleets of which constitute not less than 50 per cent of the gross tonnage of the world's merchant fleet;
(ii)  an amendment to an Annex to the Convention shall be deemed to have been accepted in accordance with the procedure specified in subparagraph (f)(iii) unless the appropriate body, at the time of its adoption, determines that the amendment shall be deemed to have been accepted on the date on which it is accepted by two thirds of the Parties, the combined merchant fleets of which constitute not less than 50 per cent of the gross tonnage of the world's merchant fleet. Nevertheless, at any time before the entry into force of an amendment to an Annex to the Convention, a Party may notify the Secretary-General of the Organization that its express approval will be necessary before the amendment enters into force for it. The latter shall bring such notification and the date of its receipt to the notice of Parties;
(iii)  an amendment to an appendix to an Annex to the Convention shall be deemed to have been accepted at the end of a period to be determined by the appropriate body at the time of its adoption, which period shall be not less than ten months, unless within that period an objection is communicated to the Organization by not less than one third of the Parties or by the Parties the combined merchant fleets of which constitute not less than 50 per cent of the gross tonnage of the world's merchant fleet whichever condition is fulfilled;
(iv)  an amendment to Protocol I to the Convention shall be subject to the same procedures as for the amendments to the Annexes to the Convention, as provided for in subparagraphs (f)(ii) or (f)(iii) above;
(v)  an amendment to Protocol II to the Convention shall be subject to the same procedures as for the amendments to an article of the Convention, as provided for in subparagraph (f)(i) above;
(g)  the amendment shall enter into force under the following conditions:
(i)  in the case of an amendment to an article of the Convention, to Protocol II, or to Protocol I or to an Annex to the Convention not under the procedure specified in subparagraph (f)(iii), the amendment accepted in conformity with the foregoing provisions shall enter into force six months after the date of its acceptance with respect to the Parties which have declared that they have accepted it;
(ii)  in the case of an amendment to Protocol I, to an appendix to an Annex or to an Annex to the Convention under the procedure specified in subparagraph (f)(iii), the amendment deemed to have been accepted in accordance with the foregoing conditions shall enter into force six months after its acceptance for all the Parties with the exception of those which, before that date, have made a declaration that they do not accept it or a declaration under subparagraph (f)(ii), that their express approval is necessary.

(3) Amendment by a Conference:

(a)  Upon the request of a Party, concurred in by at least one third of the Parties, the Organization shall convene a Conference of Parties to the Convention to consider amendments to the present Convention.
(b)  Every amendment adopted by such a Conference by a two-thirds majority of those present and voting of the Parties shall be communicated by the Secretary-General of the Organization to all Contracting Parties for their acceptance.
(c)  Unless the Conference decides otherwise, the amendment shall be deemed to have been accepted and to have entered into force in accordance with the procedures specified for that purpose in paragraph (2)(f) and (g) above.

(4)
(a)  In the case of an amendment to an Optional Annex, a reference in the present article to a "Party to the Convention" shall be deemed to mean a reference to a Party bound by that Annex.
(b)  Any Party which has declined to accept an amendment to an Annex shall be treated as a non-Party only for the purpose of application of that amendment.

(5) The adoption and entry into force of a new Annex shall be subject to the same procedures as for the adoption and entry into force of an amendment to an article of the Convention.

(6) Unless expressly provided otherwise, any amendment to the present Convention made under this article, which relates to the structure of a ship, shall apply only to ships for which the building contract is placed, or in the absence of a building contract, the keel of which is laid, on or after the date on which the amendment comes into force.

(7) Any amendment to a Protocol or to an Annex shall relate to the substance of that Protocol or Annex and shall be consistent with the articles of the present Convention.

(8) The Secretary-General of the Organization shall inform all Parties of any amendments which enter into force under the present article, together with the date on which each such amendment enters into force.

(9) Any declaration of acceptance or of objection to an amendment under the present article shall be notified in writing to the Secretary-General of the Organization. The latter shall bring such notification and the date of its receipt to the notice of the Parties to the Convention."""


# ── Gap 2 — pages 179-180: Annex II Ch.3 surveys, Reg 8 tail + Reg 9 + Reg 10 start

GAP2_LEFT = """\
2.1 Surveys of ships, as regards the enforcement of the provisions of this Annex, shall be carried out by officers of the Administration. The Administration may, however, entrust the surveys either to surveyors nominated for the purpose or to organizations recognized by it.

2.2 Such organizations, including classification societies, shall be authorized by the Administration in accordance with the provisions of the present Convention and with the Code for recognized organizations (RO Code), consisting of part 1 and part 2 (the provisions of which shall be treated as mandatory) and part 3 (the provisions of which shall be treated as recommendatory), as adopted by the Organization by resolution MEPC.237(65), as may be amended by the Organization, provided that:

.1  amendments to part 1 and part 2 of the RO Code are adopted, brought into force and take effect in accordance with the provisions of article 16 of the present Convention concerning the amendment procedures applicable to this annex;
.2  amendments to part 3 of the RO Code are adopted by the Marine Environment Protection Committee in accordance with its Rules of Procedure; and
.3  any amendments referred to in .1 and .2 adopted by the Maritime Safety Committee and the Marine Environment Protection Committee are identical and come into force or take effect at the same time, as appropriate.

2.3 An Administration nominating surveyors or recognizing organizations to conduct surveys as set forth in paragraph 2.1 of this regulation shall, as a minimum, empower any nominated surveyor or recognized organization to:

.1  require repairs to a ship; and
.2  carry out surveys if requested by the appropriate authorities of a port State.

2.4 The Administration shall notify the Organization of the specific responsibilities and conditions of the authority delegated to the nominated surveyors or recognized organizations, for circulation to Parties to the present Convention for the information of their officers.

2.5 When a nominated surveyor or recognized organization determines that the condition of the ship or its equipment does not correspond substantially with the particulars of the Certificate, or is such that the ship is not fit to proceed to sea without presenting an unreasonable threat of harm to the marine environment, such surveyor or organization shall immediately ensure that corrective action is taken and shall in due course notify the Administration. If such corrective action is not taken the Certificate should be withdrawn and the Administration shall be notified immediately, and if the ship is in a port of another Party, the appropriate authorities of the port State shall also be notified immediately. When an officer of the Administration, a nominated surveyor or a recognized organization has notified the appropriate authorities of the port State, the Government of the port State concerned shall give such officer, surveyor or organization any necessary assistance to carry out their obligations under this regulation. When applicable, the Government of the port State concerned shall take such steps as will ensure that the ship shall not sail until it can proceed to sea or leave the port for the purpose of proceeding to the nearest appropriate repair yard available without presenting an unreasonable threat of harm to the marine environment.

2.6 In every case, the Administration concerned shall fully guarantee the completeness and efficiency of the survey and shall undertake to ensure the necessary arrangements to satisfy this obligation.

3.1 The condition of the ship and its equipment shall be maintained to conform with the provisions of the present Convention to ensure that the ship in all respects will remain fit to proceed to sea without presenting an unreasonable threat of harm to the marine environment.

3.2 After any survey of the ship required under paragraph 1 of this regulation has been completed, no change shall be made in the structure, equipment, systems, fittings, arrangements or material covered by the survey, without the sanction of the Administration, except the direct replacement of such equipment and fittings.

3.3 Whenever an accident occurs to a ship or a defect is discovered which substantially affects the integrity of the ship or the efficiency or completeness of its equipment covered by this Annex, the master or owner of the ship shall report at the earliest opportunity to the Administration, the recognized organization or the nominated surveyor responsible for issuing the relevant Certificate, who shall cause investigations to be initiated to determine whether a survey as required by paragraph 1 of this regulation is necessary. If the ship is in a port of another Party, the master or owner shall also report immediately to the appropriate authorities of the port State and the nominated surveyor or recognized organization shall ascertain that such report has been made."""

GAP2_RIGHT = """\
Regulation 9
Issue or endorsement of Certificate

1 An International Pollution Prevention Certificate for the Carriage of Noxious Liquid Substances in Bulk shall be issued, after an initial or renewal survey in accordance with the provisions of regulation 8 of this Annex, to any ship intended to carry noxious liquid substances in bulk and which is engaged in voyages to ports or terminals under the jurisdiction of other Parties to the Convention.

2 Such Certificate shall be issued or endorsed either by the Administration or by any person or organization duly authorized by it. In every case, the Administration assumes full responsibility for the Certificate.

3.1 The Government of a Party to the Convention may, at the request of the Administration, cause a ship to be surveyed and, if satisfied that the provisions of this Annex are complied with, shall issue or authorize the issue of an International Pollution Prevention Certificate for the Carriage of Noxious Liquid Substances in Bulk to the ship and, where appropriate, endorse or authorize the endorsement of that Certificate on the ship, in accordance with this Annex.

3.2 A copy of the Certificate and a copy of the survey report shall be transmitted as soon as possible to the requesting Administration.

3.3 A Certificate so issued shall contain a statement to the effect that it has been issued at the request of the Administration and it shall have the same force and receive the same recognition as the Certificate issued under paragraph 1 of this regulation.

3.4 No International Pollution Prevention Certificate for the Carriage of Noxious Liquid Substances in Bulk shall be issued to a ship which is entitled to fly the flag of a State which is not a party.

4 The International Pollution Prevention Certificate for the Carriage of Noxious Liquid Substances in Bulk shall be drawn up in the form corresponding to the model given in appendix III to this Annex and shall be at least in English, French or Spanish. Where entries in an official national language of the State whose flag the ship is entitled to fly are also used, this shall prevail in the case of a dispute or discrepancy.

Regulation 10
Duration and validity of Certificate

1 An International Pollution Prevention Certificate for the Carriage of Noxious Liquid Substances in Bulk shall be issued for a period specified by the Administration which shall not exceed 5 years.

2.1 Notwithstanding the requirements of paragraph 1 of this regulation, when the renewal survey is completed within 3 months before the expiry date of the existing Certificate, the new Certificate shall be valid from the date of completion of the renewal survey to a date not exceeding 5 years from the date of expiry of the existing Certificate.

2.2 When the renewal survey is completed after the expiry date of the existing Certificate, the new Certificate shall be valid from the date of completion of the renewal survey to a date not exceeding 5 years from the date of expiry of the existing Certificate."""


# ── Gap 3 — pages 239-240: Annex IV Ch.2 surveys, Reg 4 tail + Regs 5-7 + Reg 8 start

GAP3_LEFT = """\
notify the Administration. If such corrective action is not taken, the Certificate should be withdrawn and the Administration shall be notified immediately and if the ship is in a port of another Party, the appropriate authorities of the Port State shall also be notified immediately. When an officer of the Administration, a nominated surveyor or recognized organization has notified the appropriate authorities of the Port State, the Government of the Port State concerned shall give such officer, surveyor or organization any necessary assistance to carry out their obligations under this regulation. When applicable, the Government of the Port State concerned shall take such steps as will ensure that the ship shall not sail until it can proceed to sea or leave the port for the purpose of proceeding to the nearest appropriate repair yard available without presenting an unreasonable threat of harm to the marine environment.

6 In every case, the Administration concerned shall fully guarantee the completeness and efficiency of the survey and shall undertake to ensure the necessary arrangements to satisfy this obligation.

7 The condition of the ship and its equipment shall be maintained to conform with the provisions of the present Convention to ensure that the ship in all respects will remain fit to proceed to sea without presenting an unreasonable threat of harm to the marine environment.

8 After any survey of the ship under paragraph 1 of this regulation has been completed, no change shall be made in the structure, equipment, systems, fittings, arrangements or materials covered by the survey, without the sanction of the Administration, except the direct replacement of such equipment and fittings.

9 Whenever an accident occurs to a ship or a defect is discovered which substantially affects the integrity of the ship or the efficiency or completeness of its equipment covered by this Annex, the master or owner of the ship shall report at the earliest opportunity to the Administration, the recognized organization or the nominated surveyor responsible for issuing the relevant Certificate, who shall cause investigations to be initiated to determine whether a survey as required by paragraph 1 of this regulation is necessary. If the ship is in a port of another Party, the master or owner shall also report immediately to the appropriate authorities of the Port State and the nominated surveyor or recognized organization shall ascertain that such report has been made.

Regulation 5
Issue or endorsement of Certificate

1 An International Sewage Pollution Prevention Certificate shall be issued, after an initial or renewal survey in accordance with the provisions of regulation 4 of this Annex, to any ship which is engaged in voyages to ports or offshore terminals under the jurisdiction of other Parties to the Convention. In the case of existing ships this requirement shall apply five years after the date of entry into force of this Annex.

2 Such Certificate shall be issued or endorsed either by the Administration or by any persons or organization duly authorized by it. In every case, the Administration assumes full responsibility for the Certificate."""

GAP3_RIGHT = """\
Regulation 6
Issue or endorsement of a Certificate by another Government

1 The Government of a Party to the Convention may, at the request of the Administration, cause a ship to be surveyed and, if satisfied that the provisions of this Annex are complied with, shall issue or authorize the issue of an International Sewage Pollution Prevention Certificate to the ship, and where appropriate, endorse or authorize the endorsement of that Certificate on the ship in accordance with this Annex.

2 A copy of the Certificate and a copy of the survey report shall be transmitted as soon as possible to the Administration requesting the survey.

3 A Certificate so issued shall contain a statement to the effect that it has been issued at the request of the Administration and it shall have the same force and receive the same recognition as the Certificate issued under regulation 5 of this Annex.

4 No International Sewage Pollution Prevention Certificate or UNSP Exemption Certificate shall be issued to a ship which is entitled to fly the flag of a State which is not a Party.

Regulation 7
Form of Certificate

1 The International Sewage Pollution Prevention Certificate shall be drawn up in the form corresponding to the model given in appendix I to this Annex and shall be at least in English, French or Spanish. If an official language of the issuing country is also used, this shall prevail in case of a dispute or discrepancy.

2 The International Sewage Pollution Prevention Exemption Certificate for Unmanned Non-self-propelled (UNSP) Barges shall be drawn up in the form corresponding to the model given in appendix II to this Annex and shall be at least in English, French or Spanish. If an official language of the issuing country is also used, this shall prevail in the event of a dispute or discrepancy.

Regulation 8
Duration and validity of Certificate

1 An International Sewage Pollution Prevention Certificate shall be issued for a period specified by the Administration which shall not exceed five years.

2.1 Notwithstanding the requirements of paragraph 1 of this regulation, when the renewal survey is completed within three months before the expiry date of the existing Certificate, the new Certificate shall be valid from the date of completion of the renewal survey to a date not exceeding five years from the date of expiry of the existing Certificate.

2.2 When the renewal survey is completed after the expiry date of the existing Certificate, the new Certificate shall be valid from the date of completion of the renewal survey to a date not exceeding five years from the date of expiry of the existing Certificate.

2.3 When the renewal survey is completed more than three months before the expiry date of the existing Certificate, the new Certificate shall be valid from the date of completion of the renewal survey to a date not exceeding five years from the date of completion of the renewal survey.

3 If a Certificate is issued for a period of less than five years, the Administration may extend the validity of the Certificate beyond the expiry date to the maximum period specified in paragraph 1 of this regulation.

4 If a renewal survey has been completed and a new Certificate cannot be issued or placed on board the ship before the expiry date of the existing Certificate, the person or organization authorized by the Administration may endorse the existing Certificate and such a Certificate shall be accepted as valid for a further period which shall not exceed five months from the expiry date.

5 If a ship at the time when a Certificate expires is not in a port in which it is to be surveyed, the Administration may extend the period of validity of the Certificate but this extension shall be granted only for the purpose of allowing the ship to complete its voyage to the port in which it is to be surveyed and then only in cases where it appears proper and reasonable to do so. No Certificate shall be extended for a period longer than three months, and a ship to which an extension is granted shall not, on its arrival in the port in which it is to be surveyed, be entitled by virtue of such extension to leave that port without having a new Certificate. When the renewal survey is completed, the new Certificate shall be valid to a date not exceeding five years from the date of expiry of the existing Certificate before the extension was granted."""


# Map 4/27 screenshot filenames -> the text that goes there.
# Order matches Blake's chronological capture sequence — earliest timestamp
# fixes earliest-numbered gap.
GAP_MAPPING = [
    {
        "png": "MARPOL _ IMO e-Publications - Google Chrome 4_27_2026 8_19_48 AM.png",
        "left_page": 15, "left_text": GAP1_LEFT,
        "right_page": 16, "right_text": GAP1_RIGHT,
    },
    {
        "png": "MARPOL _ IMO e-Publications - Google Chrome 4_27_2026 8_20_19 AM.png",
        "left_page": 179, "left_text": GAP2_LEFT,
        "right_page": 180, "right_text": GAP2_RIGHT,
    },
    {
        "png": "MARPOL _ IMO e-Publications - Google Chrome 4_27_2026 8_20_48 AM.png",
        "left_page": 239, "left_text": GAP3_LEFT,
        "right_page": 240, "right_text": GAP3_RIGHT,
    },
]


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    entries = manifest.setdefault("entries", {})

    written = 0
    for gap in GAP_MAPPING:
        png_path = SOURCE_DIR / gap["png"]
        if not png_path.exists():
            print(f"WARN: missing png {gap['png']!r} — skipping", file=sys.stderr)
            continue
        sha = _file_sha(png_path)
        out_path = EXTRACTED_DIR / f"{sha}.txt"
        body = (
            f"=== Left page (book p.{gap['left_page']}) ===\n\n"
            f"{gap['left_text'].strip()}\n\n"
            f"=== Right page (book p.{gap['right_page']}) ===\n\n"
            f"{gap['right_text'].strip()}\n"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
        entries[gap["png"]] = {
            "sha": sha,
            "status": "ok",
            "char_count": len(body),
            "source": "manual_transcription",
        }
        print(
            f"OK  {gap['png']}  ->  {sha[:16]}…  "
            f"pages {gap['left_page']}-{gap['right_page']}  "
            f"({len(body):,} chars)"
        )
        written += 1

    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)
    print(f"\nWrote {written} manual transcript file(s); manifest updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
