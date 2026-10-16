"""2026-10-16 security fix — attaching a document preview: the id is a UUID,
only the caller's own preview can be attached, and stale previews are purged
(app/routers/documents.py)."""
import os
import time
import uuid

import pytest
from pydantic import ValidationError

from app.config import settings
from app.routers import documents as D


@pytest.mark.parametrize("bad", ["*", "../*", "../../.env", "abc", ""])
def test_preview_id_must_be_a_uuid(bad):
    with pytest.raises(ValidationError):
        D.AttachPreviewBody(preview_id=bad)


def test_only_the_callers_own_preview_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    me, other, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    mine = tmp_path / "_previews" / str(me)
    theirs = tmp_path / "_previews" / str(other)
    mine.mkdir(parents=True)
    theirs.mkdir(parents=True)
    (mine / f"{pid}.pdf").write_bytes(b"%PDF")
    their_pid = uuid.uuid4()
    (theirs / f"{their_pid}.jpg").write_bytes(b"jpg")
    (tmp_path / ".env").write_text("SECRET=1")

    assert D.find_preview(me, pid) == (mine / f"{pid}.pdf").resolve()
    assert D.find_preview(me, their_pid) is None          # another user's preview
    assert D.find_preview(other, pid) is None
    assert D.find_preview(me, uuid.uuid4()) is None


def test_stale_previews_are_purged(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    folder = tmp_path / "_previews" / str(uuid.uuid4())
    folder.mkdir(parents=True)
    old, fresh, legacy = folder / "old.pdf", folder / "fresh.pdf", tmp_path / "_previews" / "flat.jpg"
    for f in (old, fresh, legacy):
        f.write_bytes(b"x")
    past = time.time() - 72 * 3600
    os.utime(old, (past, past))
    os.utime(legacy, (past, past))
    assert D.purge_stale_previews() == 2
    assert fresh.exists() and not old.exists() and not legacy.exists()
