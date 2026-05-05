"""
Curated-list ingest adapter for non-English flag-state regulators.

Sprint D6.47 — first batch of multilingual flag states landed via the
existing text-embedding-3-small pipeline (cross-lingual EN<->DE/ES/IT/EL
cosine similarity 0.45-0.70 in spot-check; no embedder change needed).

Sources currently served by this module:
  bg_verkehr    — Germany (BG Verkehr / deutsche-flagge.de) — language=de
  dgmm_es       — Spain  (Dirección General de la Marina Mercante)  — es
  it_capitaneria — Italy  (Guardia Costiera + MIT)                   — it
  gr_ynanp      — Greece (Hellenic Ministry of Maritime Affairs)    — el

Each source is a hand-curated list of free, publicly-accessible regulator
PDFs. The same pdfplumber-based extractor + download retry logic from
the older curated adapters (MPA/IRI/LISCR/NMA pre-D6.46) is reused via
a small per-source config registry.

License: each regulator publishes for compliance use; fair-use ingestion
into a private RAG knowledge base. Surface the original URL on cited
chunks so users can verify against the upstream source.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.6,es;q=0.6,it;q=0.6,el;q=0.6,fr;q=0.5",
}
_REQUEST_DELAY = 0.6
_TIMEOUT       = 60.0
_MAX_PDF_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class CuratedDoc:
    code:           str
    title:          str
    pdf_url:        str

    def filename_stub(self, source: str) -> str:
        return source + "_" + re.sub(r"[^a-z0-9]+", "_",
                                      self.code.lower()).strip("_")


@dataclass(frozen=True)
class SourceConfig:
    code:                  str    # "bg_verkehr"
    parent_section_number: str    # "BG Verkehr (Germany)"
    language:              str    # "de"
    source_date:           date
    docs:                  list[CuratedDoc]


# ── Curated lists (D6.47) ───────────────────────────────────────────────────
# These are gathered via web research; URLs verified to return 200 +
# application/pdf at the time of curation. New entries are added by
# editing these constants — no schema change needed.

_BG_VERKEHR_DOCS: list[CuratedDoc] = [
    # ── ISM Rundschreiben ──────────────────────────────────────────────────
    CuratedDoc("BG ISM Circ 2009/2", "ISM Rundschreiben 2009/2 — Rate-of-Turn Indicators",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2009_2_dt.pdf"),
    CuratedDoc("BG ISM Circ 2011/4", "ISM Rundschreiben 04/2011 — On-load Release/Retrieval",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2011_4_dt.pdf"),
    CuratedDoc("BG ISM Circ 2011/5", "ISM Rundschreiben 05/2011 — SOLAS V Änderungen",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2011_5_dt.pdf"),
    CuratedDoc("BG ISM Circ 2013/1 EN", "ISM Circular 01/2013 (English)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2013_1_eng.pdf"),
    CuratedDoc("BG ISM Circ 2014/4", "Rundschreiben 04/2014 — Security Training",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2014_4.pdf"),
    CuratedDoc("BG ISM Circ 2014/6 EN", "ISM Circular 06/2014 (English)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2014_6_engl.pdf"),
    CuratedDoc("BG ISM Circ 2015/4", "Early Implementation SOLAS XI-1/7 — Atmosphere Testing",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2015_4_3.pdf"),
    CuratedDoc("BG ISM Circ 2015/6", "ECDIS — Guidance for Good Practice",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/Circ2015_6_1.pdf"),
    CuratedDoc("BG ISM Circ 2018/4", "ISM Rundschreiben 2018/4 — ISM Cyber Security",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/circ2018_4_2.pdf"),
    CuratedDoc("BG ISM Circ 2020/3", "ISM Rundschreiben 2020/3 — Änderungen Seearbeitsrecht",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/circ2020_3_dt.pdf"),
    CuratedDoc("BG ISM Circ 2021/5", "ISM INFO 2021/5 — Human Element",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/circ2021_5_2_dt.pdf"),
    CuratedDoc("BG ISM Circ 01/2022", "Rundschreiben 01/2022 — Änderungen SeeArbG ab 01.08.2022",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/ism-rundschreiben/circ01-2022-aenderungen-seearbg-ab-01-08-2022.pdf"),
    # ── SOLAS Interpretations ──────────────────────────────────────────────
    CuratedDoc("BG SOLAS UI SC226", "IACS Unified Interpretations SOLAS XII (SC 226)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/interpretationen/solas/xii/ui-sc226_rev1_ul.pdf"),
    CuratedDoc("BG SOLAS UI SC191", "IACS Unified Interpretations SOLAS II-1 (SC 191)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/interpretationen/solas/ii-1/ui-sc191rev8.pdf"),
    CuratedDoc("BG SOLAS MSC.1/Circ.1572", "Unified Interpretations SOLAS II-1 and XII",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/interpretationen/solas/ii-1/msc-1-circ-1572-unified-interpretations-of-solas-chapters-ii-1-and-xii-of-the-technicalprovisions-for-mea-secretariat.pdf"),
    CuratedDoc("BG ISM Code 2018", "ISM Code 2018 (EMSA)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/interpretationen/solas/ix/ism-code-2018-emsa.pdf"),
    # ── National Requirements / Flaggenstaat ───────────────────────────────
    CuratedDoc("BG FI S/000/2020", "Flaggenstaatliche Information FI S/000/-/2020 — Definitionen",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-dienststelle/fi_s_000_2020_01-d-definitions.pdf"),
    CuratedDoc("BG NAT_REQU_DEU 2022", "National Requirements Germany (Sept 2022)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-dienststelle/nat_requ_deu.pdf"),
    CuratedDoc("BG MLC Leitfaden", "Leitfaden zur Umsetzung des Seearbeitsgesetzes",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-dienststelle/mlc-leitfaden.pdf"),
    CuratedDoc("BG MLC Heuervertrag", "Muster-Heuervertrag (Sample Seafarer Employment Agreement)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-dienststelle/muster-heuervertrag-deutsche-flagge.pdf"),
    CuratedDoc("BG MLC SeeArbUebk", "Seearbeitsübereinkommen 2006 (MLC) — German Text",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/seearbeitsuebereinkommen.pdf"),
    # ── STCW ──────────────────────────────────────────────────────────────
    CuratedDoc("BG STCW Manila", "BSH Information — STCW Manila Amendments 2010",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-bsh/info_stcw_manila.pdf"),
    CuratedDoc("BG STCW Struktur", "BSH — STCW-Übereinkommen Struktur und Kapitel",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-bsh/info_stcw.pdf"),
    CuratedDoc("BG STCW Kurse", "Zugelassene STCW-Auffrischungslehrgänge VI/1, VI/2, VI/3",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-dienststelle/zugel-kurse-schiffssicherheit-auffrischung.pdf"),
    # ── SchSV / SPS / BWM ──────────────────────────────────────────────────
    CuratedDoc("BG SchSV Frachter", "SchSV Anlage 1a Teil 6 — Frachtschiffe",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/schsv-anlage-1a-teil-6-frachtschiffe.pdf"),
    CuratedDoc("BG SchSV Trad", "SchSV Anlage 1a Teil 3 — Traditionsschiffe",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/schsv-anlage-1a-teil-3-traditionsschiffe.pdf"),
    CuratedDoc("BG SPS Code 2008", "Code über die Sicherheit von Spezialschiffen 2008 (SPS)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/sps-code-2008.pdf"),
    CuratedDoc("BG BWM Gesetz", "Ballastwasser-Gesetz (BGBl. II)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/ballastwasser-gesetz.pdf"),
    CuratedDoc("BG BWM Info BSH", "Ballastwasser-Übereinkommen (BSH-Info)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-bsh/info_ballastw-uebereink.pdf"),
    CuratedDoc("BG MEPC.312(74)", "MEPC.312(74) — E-Record Books (DE)",
               "https://www.deutsche-flagge.de/de/redaktion/dokumente/dokumente-sonstige/mepc-312-74.pdf"),
]

_DGMM_DOCS: list[CuratedDoc] = [
    CuratedDoc("DGMM IS 3/2020", "Instrucción de Servicio 3/2020 — Arrendamiento Náuticos",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/is_3-2020_arrendamiento_nauticos_2020_07_16_firmada_0.pdf"),
    CuratedDoc("DGMM RD 393/1996", "Real Decreto 393/1996 — Reglamento General de Practicaje",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-1996-6171-consolidado_0.pdf"),
    CuratedDoc("DGMM RD 1837/2000", "Real Decreto 1837/2000 — Inspección y certificación de buques",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2000-21432-consolidado.pdf"),
    CuratedDoc("DGMM Orden 18-01-2000", "Orden 18 enero 2000 — Reglamento despacho de buques",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2000-2108-consolidado.pdf"),
    CuratedDoc("DGMM RD 36/2014", "Real Decreto 36/2014 — Títulos buques pesqueros (STCW-F)",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2014-1687-consolidado.pdf"),
    CuratedDoc("DGMM RD 877/2011", "Real Decreto 877/2011 — Organizaciones reconocidas",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2011-10972-consolidado_0.pdf"),
    CuratedDoc("DGMM RD 210/2004", "Real Decreto 210/2004 — Sistema seguimiento tráfico marítimo",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2004-2752-consolidado.pdf"),
    CuratedDoc("DGMM RD 1549/2009", "Real Decreto 1549/2009 — Renovación flota pesquera",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2009-16144-consolidado.pdf"),
    CuratedDoc("DGMM RD 875/2014", "Real Decreto 875/2014 — Títulos profesionales marina mercante",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2014-10344-consolidado.pdf"),
    CuratedDoc("DGMM RD 2221/1998", "Real Decreto 2221/1998 — Registro especial de buques (Canarias)",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-1998-24949-consolidado.pdf"),
    CuratedDoc("DGMM RDL 2/2011", "RDL 2/2011 — Texto refundido Ley Puertos y Marina Mercante",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2011-16467-consolidado.pdf"),
    CuratedDoc("DGMM RD 1516/2007", "Real Decreto 1516/2007 — Tripulaciones tráfico interinsular",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2007-20272-consolidado.pdf"),
    CuratedDoc("DGMM BOE 2022-6047", "BOE-A-2022-6047 — Disposiciones generales (STCW)",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2022-6047.pdf"),
    CuratedDoc("DGMM BOE 2021-16031", "BOE-A-2021-16031 — Buques históricos",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2021-16031.pdf"),
    CuratedDoc("DGMM BOE 2017-10215", "BOE-A-2017-10215 — Disposiciones marítimas septiembre 2017",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2017-10215.pdf"),
    CuratedDoc("DGMM BOE 2010-19028", "BOE-A-2010-19028 — Disposiciones marítimas diciembre 2010",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/BOE-A-2010-19028.pdf"),
    CuratedDoc("DGMM RD 1465/1999", "Real Decreto 1465/1999",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/RD_14651999.pdf"),
    CuratedDoc("DGMM RD 97/2014", "Real Decreto 97/2014",
               "https://cdn.transportes.gob.es/portal-web-sede/documentos/RD972014.pdf"),
    CuratedDoc("DGMM Normativa 2022", "Normativa marítima — Compendio mayo 2022",
               "https://www.transportes.gob.es/recursos_mfom/paginabasica/recursos/2022-05-18_normativa_maritima_es.pdf"),
    CuratedDoc("DGMM DIM/LNM 2023", "Nota informativa DIM y LNM (octubre 2023)",
               "https://www.transportes.gob.es/recursos_mfom/paginabasica/recursos/20231019_nota_informativa_dim_y_lnm_espanol_vi.pdf"),
    CuratedDoc("DGMM Manual Maquinas", "Manual de Conocimientos Generales — Legislación marítima",
               "https://www.transportes.gob.es/recursos_mfom/paginabasica/recursos/3_ed_manual_de_maquinas.pdf"),
    CuratedDoc("DGMM PRD 2019/1159", "Proyecto RD — Directiva 2019/1159 (formación marítima)",
               "https://www.transportes.gob.es/recursos_mfom/audienciainfopublica/recursos/2021-04-21_prd_directiva_2019-1159_v1.pdf"),
]

_IT_CAPITANERIA_DOCS: list[CuratedDoc] = [
    # ── Guardia Costiera Circolari Serie Generale ──────────────────────────
    CuratedDoc("GC Circ SG 155/2019", "Circolare SG 155/2019 — Cyber risk management",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/circolare+S.G.+n.+155_2019.pdf/ac6ee5d0-c737-51da-e161-84492d835e7f?t=1749655035236"),
    CuratedDoc("GC Circ SG 158/2020", "Circolare SG 158/2020 — D.Lgs. 37/2020 ispezioni ro-ro",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/Circolare+SG+158-2020.pdf/11e80f08-7603-384f-e061-e833bfffc67e?t=1749655087668"),
    CuratedDoc("GC Circ SG 169/2023", "Circolare SG 169/2023 — Sicurezza della Navigazione",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/M_CCPP.CGCCP.REGISTRO+UFFICIALE(U).0007828.24-01-2023.pdf/12c22f9c-d818-0219-9da2-a7a2c0dd4434?t=1749655015639"),
    CuratedDoc("GC Circ SG 171/2023", "Circolare SG 171/2023 Rev.2 — Trasporto personale industriale",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/Serie+Generale+n.+171_2023Rev.2.pdf/7d8a33f2-52d1-fdbd-0c4c-fede71e60b5b?t=1751448291232"),
    CuratedDoc("GC Circ SG 35/2025", "Circolare SG 35/2025 — Combustibili alternativi",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/Circolare+n.+35_2025.pdf/36f3fc42-d447-7ebe-6504-c571bb9327bc?t=1749654628502"),
    CuratedDoc("GC Circ SG 177/2025", "Circolare SG 177/2025 — Sicurezza navigazione (ITA/EN)",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/0/Circolare_SG_177_2025+ITA_EN.pdf/b2e3fa2e-242a-2de3-57af-a14765e1df2d?t=1771949553412"),
    CuratedDoc("GC Circ MerciP 41/2022", "Circolare Merci Pericolose 41/2022",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/Circolare+serie+merci+pericolose+n.+41_2022.pdf/ac91362c-5a51-bd84-ae11-79c775b788a0?t=1749655070757"),
    CuratedDoc("GC Circ Form 40", "Circolare Formazione 40 — Primo soccorso elementare",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5756688/Circolare+n%C2%B0+40+istruzione+e+attestazione+in+materia+di+primo+soccorso+elementare+-+elementary+first+aid.pdf/9a96f8dd-9943-2295-75c3-0f0bbcfef4db?t=1751878963236"),
    CuratedDoc("GC Circ Tab Arm 002/2016", "Circolare Tabelle di Armamento 002/2016",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171215/Circolare+Tabelle+di+armamento+002-2016.pdf/5fac3375-4738-8be7-d097-43ea490e1a0b?t=1749655091792"),
    CuratedDoc("GC DD 850/2024", "Decreto Direttoriale 850/2024 — Riconoscimento enti formazione",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171913/Decreto+nr.+850.2024.pdf/62b486f7-28b8-c236-e82e-41554ed360dc?t=1749653372229"),
    CuratedDoc("GC DDC 2024.1986", "Decreto Modalità Svolgimento Corsi (consolidato 2025)",
               "https://www.guardiacostiera.gov.it/portale/documents/5158541/5171913/2024.1986+-+Decreto+Modalita+Svolgimento+Corsi+consolidato+con+modifiche+al+2025.pdf/3b209406-cd86-0d61-7ac7-20125620240c?t=1756200079200"),
    # ── Ordinanze locali campione ──────────────────────────────────────────
    CuratedDoc("GC Ord 04/2014 Bunk", "Ordinanza 04/2014 — Regolamento operazioni di bunkeraggio",
               "https://www.guardiacostiera.gov.it/portale/documents/116294/704348/04+-+2014+-+Regolamento+delle+operazioni+di+bunkeraggio+-+pdf.pdf/4e745d78-2a8c-563a-cb85-b5ffc029b393?version=1.0&t=1739516019380"),
    CuratedDoc("GC Ord 13/2025 Balneare", "Ordinanza 13/2025 — Sicurezza balneare 2025",
               "https://www.guardiacostiera.gov.it/portale/documents/315488/2008069/Ord.+13+del+29.04.2025+-+Ordinanza+di+sicurezza+balneare+2025.pdf/6d2aa0ec-2796-7887-dc71-179820b46c7c?t=1746000705229"),
    # ── MIT Lavoro Marittimo Decreti ───────────────────────────────────────
    CuratedDoc("MIT D 16/2025", "Decreto Lavoro Marittimo n.16 del 05-02-2025",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2025/02/DECRETO-n_16.05-02-2025.pdf"),
    CuratedDoc("MIT D 72/2025", "Decreto Lavoro Marittimo n.72 del 07-05-2025",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2025/05/Decreto_72.07-05-2025.pdf"),
    CuratedDoc("MIT D 75/2025", "Decreto MIT n.75 — Esami marittimi",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2025/05/Decreto-75.pdf"),
    CuratedDoc("MIT DLgs 71/2015", "Decreto Legislativo 71 del 12-05-2015 — Direttiva STCW",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2023/08/Decreto_Legislativo_numero_71_12-05-2015_all_1.pdf"),
    CuratedDoc("MIT DLgs 194/2021", "Decreto Legislativo 194 dell'08-11-2021 — Modifiche STCW",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2023/08/Decreto-Legislativo-8-novembre-2021-n.-194.pdf"),
    CuratedDoc("MIT DM 22-11-2016", "DM 22 novembre 2016 — Programmi esami marittimi",
               "https://lavoromarittimo.mit.gov.it/wp-content/uploads/2023/07/DM-22-NOVEMBRE-2016.pdf"),
]

_OCIMF_DOCS: list[CuratedDoc] = [
    # ── SIRE 2.0 program docs ───────────────────────────────────────────────
    CuratedDoc("OCIMF SIRE 2.0 Programme Intro",
               "SIRE 2.0 Programme Introduction and Guidance v1.0 (Jan 2022)",
               "https://www.ocimf.org/document-libary/628-sire-2-0-programme-introduction-and-guidance-version-1-0-january-2022/file"),
    CuratedDoc("OCIMF SIRE 2.0 User Guide",
               "Programme User Guide to SIRE 2.0 Documents (Aug 2024)",
               "https://www.ocimf.org/document-libary/841-programme-user-guide-to-sire-2-0-documents/file"),
    CuratedDoc("OCIMF SIRE 2.0 Conditions",
               "SIRE 2.0 Conditions of Participation, Policies and Procedures",
               "https://www.ocimf.org/document-libary/833-sire-2-0-conditions-of-participation-policies-and-procedures/file"),
    CuratedDoc("OCIMF SIRE 2.0 Q Library Pt1",
               "SIRE 2.0 Question Library Part 1 — Chapters 1 to 7 v1.0 (Jan 2022)",
               "https://www.ocimf.org/document-libary/630-sire-2-0-question-library-part-1-chapters-1-to-7-version-1-0-january-2022/file"),
    CuratedDoc("OCIMF SIRE 2.0 Pre-Inspection Q",
               "SIRE 2.0 Instructions for Completing the Pre-Inspection Questionnaire v1.0",
               "https://www.ocimf.org/document-libary/664-sire-2-0-instructions-for-completing-the-pre-inspection-questionnaire-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Report Format",
               "SIRE 2.0 Inspection Report Format and Transition Report Anonymisation Process v1.0",
               "https://www.ocimf.org/document-libary/796-sire-2-0-inspection-report-format-and-transition-report-anonymisation-process-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Universal Interpretations",
               "SIRE 2.0 Universal Interpretations v1.0 (Jan 2023)",
               "https://www.ocimf.org/document-libary/737-sire-2-0-universal-interpretations-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Closing Checklist",
               "SIRE 2.0 Inspection Closing Meeting Checklist v1.0 (Apr 2022)",
               "https://www.ocimf.org/document-libary/667-sire-2-0-inspection-closing-meeting-checklist-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Opening Checklist",
               "SIRE 2.0 Inspection Opening Meeting Checklist v1.0 (Apr 2022)",
               "https://www.ocimf.org/document-libary/668-sire-2-0-inspection-opening-meeting-checklist-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Negative Observation",
               "SIRE 2.0 Negative Observation Module Explanation v1.0 (Apr 2022)",
               "https://www.ocimf.org/document-libary/666-sire-2-0-negative-observation-module-explanation-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Certificate Repository",
               "SIRE 2.0 Instructions for Uploading Certificates to the Certificate Repository v1.0",
               "https://www.ocimf.org/document-libary/663-sire-2-0-instructions-for-uploading-certificates-to-the-certificate-repository-version-1-0/file"),
    CuratedDoc("OCIMF SIRE 2.0 Draft Validation",
               "SIRE 2.0 Draft Inspection Report Validation Best Practice v1.0",
               "https://www.ocimf.org/document-libary/814-sire-2-0-draft-inspection-report-validation-best-practice-version-1-0/file"),
    CuratedDoc("OCIMF SIRE Operator Quick Start",
               "SIRE Operator Access Quick Start Guide v3.26 (Jun 2022)",
               "https://www.ocimf.org/document-libary/806-sire-operator-access-quick-start-guide/file"),
    # ── Legacy SIRE / VIQ ───────────────────────────────────────────────────
    CuratedDoc("OCIMF SIRE VIQ7",
               "SIRE Vessel Inspection Questionnaire (VIQ) v7007",
               "https://www.ocimf.org/document-libary/287-sire-vessel-inspection-questionnaire-viq-ver-7007-questionnaire/file"),
    # ── Offshore + barge ────────────────────────────────────────────────────
    CuratedDoc("OCIMF OVIQ4 7300",
               "Offshore Vessel Inspection Questionnaire OVIQ4 v7300",
               "https://www.ocimf.org/document-libary/1008-oviq4-7300-questionnaire/file"),
    CuratedDoc("OCIMF OVIQ4 Small Craft 7301",
               "OVIQ4 Small Craft v7301 Questionnaire",
               "https://www.ocimf.org/document-libary/1009-oviq4-small-craft-7301-questionnaire/file"),
    CuratedDoc("OCIMF BIQ5 US v5301",
               "Barge Inspection Questionnaire BIQ5 US v5301",
               "https://www.ocimf.org/document-libary/545-biq5-us-v5301/file"),
    # ── Information papers + operational guidance ──────────────────────────
    CuratedDoc("OCIMF Marine Terminal Info Booklet",
               "Marine Terminal Information Booklet: Guidelines and Recommendations",
               "https://www.ocimf.org/document-libary/89-marine-terminal-information-booklet-guidelines-and-recommendations/file"),
    CuratedDoc("OCIMF Marine Breakaway Couplings",
               "Marine Breakaway Couplings — Information Paper",
               "https://www.ocimf.org/document-libary/133-marine-breakaway-couplings-information-paper/file"),
    CuratedDoc("OCIMF Inert Gas Systems",
               "Inert Gas Systems — Use of Inert Gas for Carriage of Flammable Oil Cargoes",
               "https://www.ocimf.org/document-libary/96-inert-gas-systems-the-use-of-inert-gas-for-the-carriage-of-flammable-oil-cargoes/file"),
    CuratedDoc("OCIMF Safety Critical Equipment",
               "Safety Critical Equipment and Spare Parts Guidance",
               "https://www.ocimf.org/document-libary/93-safety-critical-equipment-and-spare-parts-guidance/file"),
    CuratedDoc("OCIMF Human Factors Approach",
               "Human Factors Approach — A Framework to Materially Reduce Marine Risk",
               "https://www.ocimf.org/document-libary/62-human-factors-approach/file"),
    CuratedDoc("OCIMF Survival Craft Offshore",
               "Management of Survival Craft on Fixed/Floating Offshore Installations",
               "https://www.ocimf.org/document-libary/878-management-of-survival-craft-on-fixed-floating-offshore-installations/file"),
    CuratedDoc("OCIMF Danish Straits 2026",
               "Guidelines for Large Ships Transiting the Danish Straits through the Great Belt (1st ed. 2026)",
               "https://www.ocimf.org/document-libary/1067-danish-straits-guidelines/file"),
]


_GR_YNANP_DOCS: list[CuratedDoc] = [
    CuratedDoc("HMSA YA STCW Tankers", "Υπουργική Απόφαση — STCW V/1-1, V/1-2 Tankers",
               "https://www.ynanp.gr/media/documents/document_vuk6BHq.pdf"),
    CuratedDoc("HMSA YA Lesxh 2018", "YA 2415.9/59669/2018 — Λέσχη (ΦΕΚ 3400Β)",
               "https://www.ynanp.gr/media/documents/%CE%A5%CE%91_%CE%99%CE%94%CE%A1%CE%A5%CE%A3%CE%97%CE%A3_%CE%9B%CE%95%CE%A3%CE%A7%CE%97%CE%A3_3400%CE%92_10082018.pdf"),
    CuratedDoc("HMSA YA 2341.4/2020", "YA 2341.4-2-64564/2020 — MSC.428(98) (ΦΕΚ 4426Β)",
               "https://www.ynanp.gr/media/documents/2021/03/10/10._%CE%A5%CE%91_2341.4-2-64564-2020_%CE%A6%CE%95%CE%9A_4426_%CE%92-07-10-2020.pdf"),
    CuratedDoc("HMSA EG 22/2010", "Εγκύκλιος 22/08-03-2010 — Διαδικασίες Ασφαλούς Διαχείρισης",
               "https://www.ynanp.gr/media/documents/2021/03/10/22._%CE%94%CE%B9%CE%B1%CE%B4%CE%B9%CE%BA%CE%B1%CF%83%CE%AF%CE%B5%CF%82_%CE%91%CF%83%CF%86%CE%B1%CE%BB%CE%BF%CF%8D%CF%82_%CE%94%CE%B9%CE%B1%CF%87%CE%B5%CE%AF%CF%81%CE%B9%CF%83%CE%B7%CF%82_0108-03-2010.pdf"),
    CuratedDoc("HMSA ISM 1995", "Κώδικας ISM (Πειραιάς, 20-07-1995)",
               "https://www.ynanp.gr/media/documents/2021/03/10/1._%CE%9A%CE%A9%CE%94%CE%99%CE%9A%CE%91%CE%A3_ISM_0120-07-1995.pdf"),
    CuratedDoc("HMSA Odigia 97/70/EK", "Οδηγία 97/70/ΕΚ Συμβουλίου της 11ης Δεκεμβρίου",
               "https://www.ynanp.gr/media/documents/document_96h9YfO.pdf"),
    CuratedDoc("HMSA MARPOL VI", "Παράρτημα VI ΔΣ MARPOL 73/78",
               "https://www.ynanp.gr/media/documents/document_GVeKOaQ.pdf"),
    CuratedDoc("HMSA FEK B 2477/2015", "ΦΕΚ Β 2477/2015 — IMO Guidelines Scrubbers",
               "https://www.ynanp.gr/media/documents/2021/03/23/%CE%A6%CE%95%CE%9A_%CE%92_2477_2015_IMO_Guidelines_scrubbers.pdf"),
    CuratedDoc("HMSA FEK B 1957/2013", "ΦΕΚ Β 1957/2013 — MARPOL τροποποιήσεις",
               "https://www.ynanp.gr/media/documents/2021/03/23/%CE%A6%CE%95%CE%9A_%CE%92_1957_2013_%CE%9C%CE%B5%CF%84%CE%B1%CE%B2%CE%AF%CE%B2%CE%B1%CF%83%CE%B7_%CE%B1%CF%81%CE%BC%CE%BF%CE%B4._%CF%85%CF%80%CE%BF%CE%B3%CF%81%CE%B1%CF%86%CE%AE%CF%82_%CF%84%CF%81%CE%BF%CF%80.MARPOL.pdf"),
    CuratedDoc("HMSA EgPThP-1", "Μόνιμη Εγκύκλιος Π.Θ.Π-1η — Απορρίμματα Πλοίων (MARPOL V)",
               "https://www.ynanp.gr/media/documents/2021/03/23/%CE%9C%CE%9F%CE%9D%CE%99%CE%9C%CE%97_%CE%95%CE%93%CE%9A%CE%A5%CE%9A%CE%9B%CE%99%CE%9F%CE%A3_1%CE%B7_signed.pdf"),
    CuratedDoc("HMSA Reg 2020/411", "Κανονισμός (ΕΕ) 2020/411 — Maritime",
               "https://www.ynanp.gr/media/documents/%CE%9A%CE%91%CE%9D%CE%9F%CE%9D%CE%99%CE%A3%CE%9C%CE%9F%CE%A32020_411.pdf"),
    CuratedDoc("HMSA PD 13", "Προεδρικό Διάταγμα 13 — Οργανισμός Υπουργείου Ναυτιλίας",
               "https://www.ynanp.gr/media/documents/document_cEKkIkc.pdf"),
    CuratedDoc("HMSA ND 187/1973", "ΝΔ 187/1973 — Κώδικας Δημοσίου Ναυτικού Δικαίου",
               "https://www.ynanp.gr/media/documents/document_67h31UC.pdf"),
    CuratedDoc("HMSA PD 38/2011", "ΠΔ 38/2011 — Νέα ειδικευμένα άτομα (passenger ships)",
               "https://www.ynanp.gr/media/documents/%CE%A0%CE%94_38_2011_%CE%9D%CE%95%CE%91_%CE%95%CE%99%CE%94%CE%99%CE%9A%CE%95%CE%A5%CE%9C%CE%95%CE%9D%CE%91_%CE%91%CE%A4%CE%9F%CE%9C%CE%91.pdf"),
]


_CONFIGS: dict[str, SourceConfig] = {
    "bg_verkehr": SourceConfig(
        code="bg_verkehr",
        parent_section_number="BG Verkehr (Germany)",
        language="de",
        source_date=date(2026, 5, 1),
        docs=_BG_VERKEHR_DOCS,
    ),
    "dgmm_es": SourceConfig(
        code="dgmm_es",
        parent_section_number="DGMM (Spain)",
        language="es",
        source_date=date(2026, 5, 1),
        docs=_DGMM_DOCS,
    ),
    "it_capitaneria": SourceConfig(
        code="it_capitaneria",
        parent_section_number="Capitanerie di Porto + MIT (Italy)",
        language="it",
        source_date=date(2026, 5, 1),
        docs=_IT_CAPITANERIA_DOCS,
    ),
    "gr_ynanp": SourceConfig(
        code="gr_ynanp",
        parent_section_number="HMSA / YNANP (Greece)",
        language="el",
        source_date=date(2026, 5, 1),
        docs=_GR_YNANP_DOCS,
    ),
    # Sprint D6.50 — OCIMF public layer. Tier-4 industry guidance (not a
    # flag-state) but uses the same curated-list adapter shape. Limited
    # to free, publicly-downloadable PDFs from ocimf.org. The full SIRE
    # 2.0 question library beyond Part 1 + ISGOTT 6th + MEG-4 + similar
    # member-only publications are NOT ingested — those need OCIMF
    # membership and are flagged in the user-facing UI as paywalled.
    "ocimf": SourceConfig(
        code="ocimf",
        parent_section_number="OCIMF Public Layer",
        language="en",
        source_date=date(2026, 5, 2),
        docs=_OCIMF_DOCS,
    ),
}


# ── Ingest API factory ───────────────────────────────────────────────────────
# Each per-source adapter module imports SOURCE / TITLE_NUMBER /
# SOURCE_DATE / discover_and_download / parse_source / get_source_date
# from this factory.

def make_adapter(source_key: str):
    cfg = _CONFIGS[source_key]

    class _Adapter:
        SOURCE = cfg.code
        TITLE_NUMBER = 0
        SOURCE_DATE = cfg.source_date

        @staticmethod
        def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
            return _discover_and_download(cfg, raw_dir, failed_dir, console)

        @staticmethod
        def parse_source(raw_dir: Path) -> list[Section]:
            return _parse_source(cfg, raw_dir)

        @staticmethod
        def get_source_date(raw_dir: Path) -> date:
            return cfg.source_date

    return _Adapter


# ── Internal: shared download + parse logic ──────────────────────────────────


def _discover_and_download(cfg: SourceConfig, raw_dir: Path,
                           failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, doc in enumerate(cfg.docs, 1):
            stub = doc.filename_stub(cfg.code)
            out_path = raw_dir / f"{stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                if i == 1 or i == len(cfg.docs) or i % 10 == 0:
                    console.print(f"  Downloading {doc.code} ({i}/{len(cfg.docs)})…")
                resp = client.get(doc.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                if len(resp.content) > _MAX_PDF_BYTES:
                    raise ValueError(f"PDF too large ({len(resp.content)/1e6:.1f} MB)")
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("%s %s: download failed — %s", cfg.code, doc.code, exc)
                _write_failure(cfg, doc, exc, failed_dir)
            time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": d.code, "title": d.title, "pdf_url": d.pdf_url}
            for d in cfg.docs
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def _parse_source(cfg: SourceConfig, raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"{cfg.code} index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        doc = CuratedDoc(code=e["code"], title=e["title"], pdf_url=e["pdf_url"])
        stub = doc.filename_stub(cfg.code)
        in_path = raw_dir / f"{stub}.pdf"
        if not in_path.exists():
            logger.warning("%s %s: PDF missing, skipping", cfg.code, doc.code)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("%s %s: extraction failed — %s", cfg.code, doc.code, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("%s %s: text too short (%d), skipping", cfg.code, doc.code, len(text))
            continue
        sections.append(Section(
            source=cfg.code, title_number=0,
            section_number=doc.code,
            section_title=doc.title,
            full_text=text,
            up_to_date_as_of=cfg.source_date,
            parent_section_number=cfg.parent_section_number,
            published_date=cfg.source_date,
            language=cfg.language,
        ))
    logger.info("%s: parsed %d sections from %d doc(s)",
                cfg.code, len(sections), len(entries))
    return sections


_LARGE_PDF_BYTES = 3 * 1024 * 1024  # 3 MB


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a PDF.

    Uses pdfplumber for small files (good table handling, layout-aware)
    and shells out to Poppler's pdftotext for files larger than 3 MB
    or when pdfplumber fails — pdftotext is a streaming C extractor
    that uses ~30 MB regardless of input size, while pdfplumber's
    memory footprint scales with content density and OOM-kills the
    prod worker on image-heavy PDFs (Sprint D6.50 OCIMF SIRE Operator
    Quick Start incident).
    """
    file_size = pdf_path.stat().st_size
    if file_size > _LARGE_PDF_BYTES:
        return _extract_via_pdftotext(pdf_path)

    try:
        page_texts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                t = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", t)
                t = re.sub(r"[ \t]+", " ", t)
                t = re.sub(r"\n{3,}", "\n\n", t)
                page_texts.append(t.strip())
        return "\n\n".join(p for p in page_texts if p)
    except Exception as exc:
        logger.warning(
            "pdfplumber failed on %s (%s); falling back to pdftotext",
            pdf_path.name, exc,
        )
        return _extract_via_pdftotext(pdf_path)


def _extract_via_pdftotext(pdf_path: Path) -> str:
    """Streaming text extraction via Poppler's pdftotext.
    Memory-bounded regardless of input size."""
    import subprocess
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, timeout=120, check=True,
        )
    except Exception as exc:
        logger.warning("pdftotext failed on %s: %s", pdf_path.name, exc)
        return ""
    text = out.stdout.decode("utf-8", errors="replace")
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _write_failure(cfg: SourceConfig, doc: CuratedDoc, exc: Exception,
                   failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": doc.code,
        "url": doc.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    stub = doc.filename_stub(cfg.code)
    (failed_dir / f"{stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
