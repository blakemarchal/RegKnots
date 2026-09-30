"""2026-09-30 — the monthly guidance refresh ends with a tesseract OCR pass."""
import subprocess

from app import tasks


def test_ocr_runs_each_source_through_the_capped_wrapper(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "uscg_cvc" in cmd:
            raise subprocess.TimeoutExpired(cmd, 3600)          # one failure stops nothing
        return subprocess.CompletedProcess(cmd, 0, "0 scanned PDFs without OCR text", "")

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    tasks._run_ocr(["nvic", "uscg_cvc", "uscg_towing"])
    assert [c[1:] for c in calls] == [["--ocr", "--source", s] for s in ("nvic", "uscg_cvc", "uscg_towing")]
    assert all(c[0].endswith("run_ingest.sh") for c in calls)


def test_the_monthly_refresh_ocrs_after_its_ingests(monkeypatch):
    order = []
    monkeypatch.setattr(tasks, "_run_ingest_sources", lambda sources, extra_args=(): order.append("ingest") or [])
    monkeypatch.setattr(tasks, "_run_ocr", lambda sources: order.append(("ocr", tuple(sources))))
    tasks.update_uscg_guidance.run()
    assert order == ["ingest", ("ocr", tuple(tasks._OCR_SOURCES))]
