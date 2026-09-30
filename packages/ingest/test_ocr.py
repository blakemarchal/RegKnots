"""2026-09-30 — tesseract OCR into adapter sidecars (no tesseract needed here)."""
import json
import subprocess
from pathlib import Path

from ingest import ocr
from ingest.sources import uscg_docs as u


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4")
    return path


def test_nvic_targets_are_scans_without_a_sidecar(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw" / "nvic", tmp_path / "ocr" / "nvic"
    raw.mkdir(parents=True)
    out.mkdir(parents=True)
    (raw / "index.json").write_text(json.dumps([{"number": n} for n in ("02-23", "10-02", "01-26", "03-75")]))
    for n in ("02-23", "10-02", "01-26"):
        _pdf(raw / f"{n}.pdf")                              # 03-75: no PDF on disk
    (out / "10-02.txt").write_text("already OCR'd")
    monkeypatch.setattr(ocr, "_first_pages_have_text", lambda pdf, n: False)
    monkeypatch.setattr(u, "pdf_text", lambda p: "" if p.stem != "01-26" else "text layer " * 50)
    assert [t.doc_id for t in ocr.nvic_targets(raw, out)] == ["NVIC 02-23"]
    assert [t.doc_id for t in ocr.nvic_targets(raw, out, force=True)] == ["NVIC 02-23", "NVIC 10-02"]
    assert ocr.nvic_targets(raw, out, only=["01-26"]) == []


def test_listing_targets_use_the_file_stem(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw" / "uscg_cvc", tmp_path / "ocr" / "uscg_cvc"
    raw.mkdir(parents=True)
    docs = [u.Doc(doc_id="CG-CVC PL 15-06 CH-2", title="", url="", filename="CG-CVC_PL_15-06_CH-2.pdf"),
            u.Doc(doc_id="CG-CVC PL 21-03", title="", url="", filename="CG-CVC_PL_21-03.pdf")]
    u.write_index(raw, docs)
    for d in docs:
        _pdf(raw / d.filename)
    monkeypatch.setattr(ocr, "_first_pages_have_text", lambda pdf, n: False)
    monkeypatch.setattr(u, "pdf_text", lambda p: "" if "15-06" in p.name else "Doublers on towing vessels. " * 10)
    [t] = ocr.listing_targets(raw, out)
    assert t.doc_id == "CG-CVC PL 15-06 CH-2" and t.out == out / "CG-CVC_PL_15-06_CH-2.txt"
    # a PDF whose first pages have text is never fully extracted
    monkeypatch.setattr(ocr, "_first_pages_have_text", lambda pdf, n: True)
    monkeypatch.setattr(u, "pdf_text", lambda p: (_ for _ in ()).throw(AssertionError("slow path")))
    assert ocr.listing_targets(raw, out) == []


def test_ocr_pdf_reads_pages_in_order(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[0])
        if cmd[0] == "pdftoppm":
            prefix = Path(cmd[-1])
            for n in (10, 2, 1):                             # pdftoppm pads; sort by number
                prefix.with_name(f"p-{n:02d}.png").write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        assert kw["env"]["OMP_THREAD_LIMIT"] == "1"
        return subprocess.CompletedProcess(cmd, 0, f"page {Path(cmd[1]).stem}\n", "")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    text = ocr.ocr_pdf(_pdf(tmp_path / "x.pdf"))
    assert text == "page p-01\n\fpage p-02\n\fpage p-10\n"
    assert calls == ["pdftoppm", "tesseract", "tesseract", "tesseract"]
