"""
Slide renderer: PPTX / PDF → letterboxed 1920×1080 PNG frames.

Library choice — pdf2image vs. pymupdf:
  pdf2image wraps poppler's pdftoppm, which is already installed in the Docker
  image via poppler-utils.  It returns PIL.Image objects that compose naturally
  with Pillow (already a project dependency), and adds zero native binaries.
  PyMuPDF ships its own ~15 MB MuPDF wheel and would be the right pick if
  poppler were absent; here pdf2image is the lower-overhead option.
  Both libraries support Python 3.13.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

TARGET_W = 1920
TARGET_H = 1080
RENDER_DPI = 150
# LibreOffice occasionally hangs on malformed presentations; kill it after this.
LIBREOFFICE_TIMEOUT = 120  # seconds


class SlideRenderError(RuntimeError):
    """Raised when slide rendering fails at any stage."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _letterbox(img: Image.Image) -> Image.Image:
    """Fit *img* into TARGET_W×TARGET_H with black bars; never distort."""
    iw, ih = img.size
    scale = min(TARGET_W / iw, TARGET_H / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh), Image.LANCZOS)
    frame = Image.new("RGB", (TARGET_W, TARGET_H), (0, 0, 0))
    frame.paste(resized, ((TARGET_W - nw) // 2, (TARGET_H - nh) // 2))
    return frame


def _pptx_to_pdf(pptx_path: Path, work_dir: Path) -> Path:
    """Convert *pptx_path* to PDF with LibreOffice headless."""
    pdf_dir = work_dir / "_pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    lo_profile = work_dir / "_lo_profile"

    cmd = [
        "libreoffice",
        "--headless",
        f"-env:UserInstallation=file://{lo_profile}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(pdf_dir),
        str(pptx_path),
    ]
    logger.info("LibreOffice: converting %s to PDF", pptx_path.name)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=LIBREOFFICE_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise SlideRenderError(
            f"LibreOffice timed out after {LIBREOFFICE_TIMEOUT}s converting {pptx_path.name}"
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise SlideRenderError(
            f"LibreOffice failed (exit {result.returncode}) for {pptx_path.name}:\n{stderr}"
        )

    expected = pdf_dir / (pptx_path.stem + ".pdf")
    if expected.exists():
        return expected

    pdfs = list(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SlideRenderError(
            f"LibreOffice produced no PDF from {pptx_path.name} "
            f"(returncode=0 but output dir is empty)"
        )
    return pdfs[0]


def _pdf_to_pngs(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Rasterize every page of *pdf_path* to slide_NNNN.png in *output_dir*."""
    # Deferred import so the rest of the module loads even if pdf2image is absent
    # in development environments outside Docker.
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise SlideRenderError(
            "pdf2image is not installed. Add it to requirements.txt and rebuild the image."
        ) from exc

    logger.info("Rasterizing %s at %d dpi", pdf_path.name, RENDER_DPI)
    try:
        pages: list[Image.Image] = convert_from_path(str(pdf_path), dpi=RENDER_DPI)
    except Exception as exc:
        raise SlideRenderError(f"PDF rasterization failed for {pdf_path.name}: {exc}") from exc

    if not pages:
        raise SlideRenderError(f"No pages found in {pdf_path.name}")

    results: list[Path] = []
    for i, page in enumerate(pages, start=1):
        out = output_dir / f"slide_{i:04d}.png"
        _letterbox(page).save(str(out), format="PNG")
        results.append(out)
        logger.debug("Wrote %s (%dx%d)", out.name, TARGET_W, TARGET_H)

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_slides(input_path: "str | Path", output_dir: "str | Path") -> list[Path]:
    """Convert a PPTX or PDF file into 1920×1080 letterboxed PNG frames.

    Args:
        input_path: Path to a .pptx, .ppt, or .pdf file.
        output_dir: Directory where slide_0001.png … slide_NNNN.png are written.
                    Created automatically if it does not exist.

    Returns:
        Sorted list of Paths to the generated PNG files.

    Raises:
        SlideRenderError: on any conversion failure (bad file, LibreOffice
            crash/timeout, PDF parse error, missing output).
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = input_path.suffix.lower()
    if suffix not in {".pptx", ".ppt", ".pdf"}:
        raise SlideRenderError(f"Unsupported file type: {suffix!r} — expected .pptx, .ppt, or .pdf")
    if not input_path.exists():
        raise SlideRenderError(f"Input file not found: {input_path}")

    logger.info("render_slides: %s → %s", input_path.name, output_dir)

    if suffix in {".pptx", ".ppt"}:
        # Use a temp dir for LibreOffice's intermediate PDF and user profile;
        # cleaned up automatically even if an exception is raised.
        with tempfile.TemporaryDirectory(prefix="slide_render_") as tmp:
            pdf_path = _pptx_to_pdf(input_path, Path(tmp))
            slides = _pdf_to_pngs(pdf_path, output_dir)
    else:
        slides = _pdf_to_pngs(input_path, output_dir)

    missing = [p for p in slides if not p.exists()]
    if missing:
        raise SlideRenderError(
            f"{len(missing)} PNG file(s) missing after render (first: {missing[0].name})"
        )

    logger.info("render_slides: produced %d slides from %s", len(slides), input_path.name)
    return slides
