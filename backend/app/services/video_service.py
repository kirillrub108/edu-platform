import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

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

        # LibreOffice names the output after the input stem
        pdf_name = Path(pptx_path).stem + ".pdf"
        pdf_path = os.path.join(pdf_dir, pdf_name)
        if not os.path.exists(pdf_path):
            # Fallback: pick any .pdf in the dir (handles edge-case naming)
            pdfs = list(Path(pdf_dir).glob("*.pdf"))
            if not pdfs:
                raise RuntimeError(f"LibreOffice produced no PDF from {pptx_path}")
            pdf_path = str(pdfs[0])

        logger.info("Rasterizing PDF: %s", pdf_path)
        _run([
            "pdftoppm", "-png", "-r", "150",
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

        for idx, (img, aud) in enumerate(zip(image_paths, audio_paths)):
            seg_path = str(work_dir / f"_seg_{idx:04d}.mp4")
            logger.info("Encoding segment %d/%d", idx + 1, total)
            _run([
                "ffmpeg", "-y",
                "-loop", "1", "-i", img,
                "-i", aud,
                "-c:v", "libx264", "-tune", "stillimage",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                seg_path,
            ])
            segment_paths.append(seg_path)
            if progress_cb:
                progress_cb(idx + 1, total)

        list_file = work_dir / "_concat.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in segment_paths:
                f.write(f"file '{seg}'\n")

        logger.info("Concatenating %d segments → %s", total, output_path)
        _run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            output_path,
        ])

        for seg in segment_paths:
            try:
                os.remove(seg)
            except OSError:
                pass
        try:
            os.remove(list_file)
        except OSError:
            pass

        return output_path


video_service = VideoService()
