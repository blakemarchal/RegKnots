"""Inspect a GovDelivery bulletin HTML snapshot for structure + self-references."""
import re
import sys

for path in sys.argv[1:]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        html = fh.read()
    print(f"=== {path} ===")

    m = re.search(r"<h1 class=['\"]bulletin_subject['\"]>(.*?)</h1>", html, re.S)
    print(f"  SUBJECT: {m.group(1).strip()[:90] if m else '?'}")

    m = re.search(r"<span class=['\"]dateline[^'\"]*['\"]>(.*?)</span>", html, re.S)
    print(f"  DATE:    {m.group(1).strip() if m else '?'}")

    pdfs = re.findall(r"href=['\"]([^'\"]+\.pdf)['\"]", html, re.I)
    print(f"  PDFs:    {len(pdfs)} -> {pdfs[:3]}")

    body_m = re.search(r"<div class=['\"]bulletin_body['\"][^>]*>(.*?)</div>\s*<div", html, re.S)
    body_html = body_m.group(1) if body_m else html
    txt = re.sub(r"<[^>]+>", " ", body_html)
    txt = re.sub(r"\s+", " ", txt).strip()

    print(f"  BODY LENGTH: {len(txt)} chars")
    print(f"  BODY PREVIEW: {txt[:200]}")

    for pat in [r"\bsupersede\w*", r"\breplaces?\b", r"\bcancels?\b",
                r"\bupdated by\b", r"\bsupplants?\b"]:
        for m in re.finditer(pat, txt, re.I):
            s, e = max(0, m.start() - 50), min(len(txt), m.end() + 80)
            print(f"  SUPERSESSION [{pat}]: ...{txt[s:e]}...")

    for m in re.finditer(
        r"(MSIB|NVIC|Policy Letter|PL|ALCOAST|CG-MMC|CG-CVC|CG-OES)\s*(?:No\.?|#)?\s*(\d{1,3}[-/]\d{2,4})",
        txt, re.I,
    ):
        print(f"  DOC-REF: {m.group(0).strip()}")
    print()
