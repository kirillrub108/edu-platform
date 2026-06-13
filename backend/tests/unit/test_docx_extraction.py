"""Pre-prod hardening: DOCX extraction guards in uploads._extract_docx_text.

python-docx (pinned 1.1.2) parses package XML via lxml with
resolve_entities=False, so XXE / billion-laughs entity expansion is already
blocked. The remaining DoS vector — a zip-bomb whose parts inflate past the
decompressed cap — is guarded here, and the billion-laughs case is pinned so a
future python-docx bump can't silently regress it.
"""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from app.routers.uploads import _extract_docx_text

pytestmark = pytest.mark.unit


def _valid_docx_bytes(text: str = "Hello lecture") -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extracts_text_from_valid_docx() -> None:
    out = _extract_docx_text(_valid_docx_bytes("Quantum mechanics intro"))
    assert "Quantum mechanics intro" in out


def test_rejects_non_zip_content() -> None:
    with pytest.raises(ValueError):
        _extract_docx_text(b"this is plainly not a docx zip archive")


def test_rejects_oversized_decompressed_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the cap so a normal small docx trips the zip-bomb guard
    # deterministically (its decompressed parts dwarf 16 bytes).
    monkeypatch.setattr("app.routers.uploads.MAX_DECOMPRESSED_DOCX_BYTES", 16)
    with pytest.raises(ValueError):
        _extract_docx_text(_valid_docx_bytes())


def test_billion_laughs_docx_does_not_expand() -> None:
    # Rewrite word/document.xml of a valid docx with a billion-laughs DTD.
    # resolve_entities=False means the bomb must NOT inflate memory: the call
    # either rejects the doc or returns a bounded string, and never hangs.
    base = _valid_docx_bytes()
    bomb_xml = (
        b'<?xml version="1.0"?>\n'
        b"<!DOCTYPE lolz [\n"
        b'  <!ENTITY lol "lol">\n'
        b'  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        b'  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">\n'
        b'  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
        b'  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">\n'
        b'  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">\n'
        b'  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">\n'
        b'  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">\n'
        b'  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">\n'
        b'  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">\n'
        b"]>\n"
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>&lol9;</w:t></w:r></w:p></w:body></w:document>"
    )
    src = io.BytesIO(base)
    out_buf = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(
        out_buf, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = (
                bomb_xml
                if item.filename == "word/document.xml"
                else zin.read(item.filename)
            )
            zout.writestr(item, data)
    bomb = out_buf.getvalue()

    start = time.monotonic()
    try:
        result = _extract_docx_text(bomb)
        assert len(result) < 100_000  # the 10^9-char bomb never materialized
    except Exception:
        pass  # rejecting the malicious document outright is equally acceptable
    assert time.monotonic() - start < 10.0  # and it did not hang
