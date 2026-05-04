"""
Shared pytest fixtures for the backend test suite.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Minimal PDF factory
# ---------------------------------------------------------------------------

def _make_minimal_pdf(width: int = 792, height: int = 612) -> bytes:
    """
    Build a valid 1-page PDF in memory without any external dependency.
    Width/height are in PDF user units (1 pt = 1/72 inch).
    Default 792×612 pt ≈ 11"×8.5" landscape (roughly 16:9 proportions).
    """
    obj1 = b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
    obj3 = (
        f"3 0 obj\n"
        f"<</Type/Page/Parent 2 0 R"
        f"/MediaBox[0 0 {width} {height}]"
        f"/Resources<<>>>>\n"
        f"endobj\n"
    ).encode()

    header = b"%PDF-1.4\n"
    buf = header
    offsets: dict[int, int] = {}

    for n, obj in [(1, obj1), (2, obj2), (3, obj3)]:
        offsets[n] = len(buf)
        buf += obj

    xref_pos = len(buf)
    xref = b"xref\n0 4\n"
    xref += b"0000000000 65535 f \n"
    for n in (1, 2, 3):
        xref += f"{offsets[n]:010d} 00000 n \n".encode()

    buf += xref
    buf += b"trailer\n<</Size 4/Root 1 0 R>>\n"
    buf += f"startxref\n{xref_pos}\n%%EOF\n".encode()
    return buf


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Writable directory that acts as tests/fixtures/ for this session."""
    d = tmp_path_factory.mktemp("fixtures")
    return d


@pytest.fixture(scope="session")
def sample_pdf(fixtures_dir: Path) -> Path:
    """A minimal valid 1-page PDF in landscape orientation (roughly 16:9)."""
    pdf_path = fixtures_dir / "test_slide.pdf"
    pdf_path.write_bytes(_make_minimal_pdf(width=792, height=612))
    return pdf_path
