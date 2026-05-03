import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pptx import Presentation

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> None:
    """Run a subprocess and raise RuntimeError with stderr on failure."""
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd[:4])}\n{stderr}"
        )


def _slide_number(path: str) -> int:
    m = re.search(r"(\d+)", Path(path).stem)
    return int(m.group(1)) if m else 0


class VideoService:
    """Convert PPTX to per-slide images and assemble a final MP4 from images + audio."""

    # Standard frame rate for output video — keeps concat segments uniform.
    FRAME_RATE = 25

    def extract_slide_texts(self, pptx_path: str) -> list[str]:
        """Extract visible text from every slide. Used as alignment hints for the LLM."""
        if Path(pptx_path).suffix.lower() not in {".pptx", ".ppt"}:
            logger.info(
                "Skipping text extraction for non-PPTX file: %s", pptx_path
            )
            return []

        try:
            prs = Presentation(pptx_path)
        except Exception:
            logger.exception("Failed to open PPTX for text extraction: %s", pptx_path)
            return []

        slide_texts: list[str] = []
        for slide in prs.slides:
            parts: list[str] = []
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        parts.append(line)
            slide_texts.append("\n".join(parts))
        return slide_texts

    def convert_pptx_to_images(self, pptx_path: str, output_dir: str) -> list[str]:
        os.makedirs(output_dir, exist_ok=True)

        pdf_dir = os.path.join(output_dir, "_pdf")
        os.makedirs(pdf_dir, exist_ok=True)

        logger.info("Converting PPTX to PDF: %s", pptx_path)
        lo_user_dir = os.path.join(output_dir, "_lo_profile")
        _run([
            "libreoffice", "--headless",
            f"-env:UserInstallation=file://{lo_user_dir}",
            "--convert-to", "pdf",
            "--outdir", pdf_dir,
            pptx_path,
        ])

        pdf_name = Path(pptx_path).stem + ".pdf"
        pdf_path = os.path.join(pdf_dir, pdf_name)
        if not os.path.exists(pdf_path):
            pdfs = list(Path(pdf_dir).glob("*.pdf"))
            if not pdfs:
                raise RuntimeError(f"LibreOffice produced no PDF from {pptx_path}")
            pdf_path = str(pdfs[0])

        logger.info("Rasterizing PDF: %s", pdf_path)
        _run([
            "pdftoppm", "-png", "-r", "300",
            "-aa", "yes", "-aaVector", "yes",
            pdf_path,
            os.path.join(output_dir, "slide"),
        ])

        images = sorted(
            (str(p) for p in Path(output_dir).glob("slide-*.png")),
            key=_slide_number,
        )
        if not images:
            raise RuntimeError(f"No slides produced from {pptx_path}")
        logger.info("Produced %d slide images", len(images))
        return images

    def build_video(
        self,
        image_paths: list[str],
        audio_paths: list[str],
        output_path: str,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> str:
        if len(image_paths) != len(audio_paths):
            raise ValueError(
                f"Image/audio count mismatch: {len(image_paths)} vs {len(audio_paths)}"
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        work_dir = Path(output_path).parent
        segment_paths: list[str] = []
        total = len(image_paths)
        fr = self.FRAME_RATE

        for idx, (img, aud) in enumerate(zip(image_paths, audio_paths)):
            # MKV segments preserve exact timestamps; concat demuxer joins them
            # without the PTS drift that the concat: protocol accumulates.
            seg_path = str(work_dir / f"_seg_{idx:04d}.mkv")
            logger.info("Encoding segment %d/%d", idx + 1, total)
            _run([
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fr), "-i", img,
                "-i", aud,
                "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium",
                "-r", str(fr),
                "-bf", "0",  # no B-frames → zero encoder delay at segment boundaries
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                seg_path,
            ])
            segment_paths.append(seg_path)
            if progress_cb:
                progress_cb(idx + 1, total)

        logger.info("Concatenating %d segments → %s", total, output_path)
        list_path = str(work_dir / "_concat_list.txt")
        with open(list_path, "w") as fh:
            for seg in segment_paths:
                fh.write(f"file '{seg}'\n")

        _run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ])

        for seg in segment_paths:
            try:
                os.remove(seg)
            except OSError:
                pass
        try:
            os.remove(list_path)
        except OSError:
            pass

        return output_path


video_service = VideoService()
