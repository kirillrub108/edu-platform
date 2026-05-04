"""
Tests for app/utils/slide_renderer.py

Requirements:
  - poppler-utils installed (pdftoppm available)
  - pdf2image Python package installed

Run inside the backend Docker container or a local env with both.
To skip when poppler is absent:  pytest -m "not integration"
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

# Skip the entire module if pdf2image or poppler (pdftoppm) are unavailable.
pdf2image = pytest.importorskip("pdf2image", reason="pdf2image not installed")
if not shutil.which("pdftoppm"):
    pytest.skip("pdftoppm (poppler-utils) not found", allow_module_level=True)

from app.utils.slide_renderer import (
    TARGET_H,
    TARGET_W,
    SlideRenderError,
    render_slides,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size  # (width, height)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderSlidesFromPdf:
    def test_returns_png_list(self, sample_pdf: Path, tmp_path: Path) -> None:
        slides = render_slides(sample_pdf, tmp_path / "out")
        assert len(slides) >= 1, "Expected at least one slide"
        assert all(p.suffix == ".png" for p in slides)

    def test_naming_convention(self, sample_pdf: Path, tmp_path: Path) -> None:
        slides = render_slides(sample_pdf, tmp_path / "out")
        assert slides[0].name == "slide_0001.png"

    def test_output_is_1920x1080(self, sample_pdf: Path, tmp_path: Path) -> None:
        """Every PNG must be exactly TARGET_W×TARGET_H regardless of source aspect ratio."""
        slides = render_slides(sample_pdf, tmp_path / "out")
        for slide in slides:
            w, h = _png_size(slide)
            assert w == TARGET_W, f"{slide.name}: width {w} != {TARGET_W}"
            assert h == TARGET_H, f"{slide.name}: height {h} != {TARGET_H}"

    def test_files_exist_on_disk(self, sample_pdf: Path, tmp_path: Path) -> None:
        slides = render_slides(sample_pdf, tmp_path / "out")
        for slide in slides:
            assert slide.exists(), f"Missing: {slide}"

    def test_output_dir_created_automatically(
        self, sample_pdf: Path, tmp_path: Path
    ) -> None:
        deep = tmp_path / "a" / "b" / "c"
        assert not deep.exists()
        render_slides(sample_pdf, deep)
        assert deep.exists()

    def test_slides_are_sorted(self, sample_pdf: Path, tmp_path: Path) -> None:
        slides = render_slides(sample_pdf, tmp_path / "out")
        names = [p.name for p in slides]
        assert names == sorted(names)


class TestRenderSlidesErrors:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SlideRenderError, match="not found"):
            render_slides(tmp_path / "ghost.pdf", tmp_path / "out")

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "file.docx"
        bad.write_text("dummy")
        with pytest.raises(SlideRenderError, match="Unsupported file type"):
            render_slides(bad, tmp_path / "out")

    def test_corrupt_pdf_raises(self, tmp_path: Path) -> None:
        bad_pdf = tmp_path / "bad.pdf"
        bad_pdf.write_bytes(b"%PDF-1.4\nthis is not a real pdf\n%%EOF\n")
        with pytest.raises(SlideRenderError):
            render_slides(bad_pdf, tmp_path / "out")
