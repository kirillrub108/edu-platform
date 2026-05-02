import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoService:
    """Convert PPTX to per-slide images and assemble a final MP4 from images + audio."""

    def convert_pptx_to_images(self, pptx_path: str, output_dir: str) -> list[str]:
        os.makedirs(output_dir, exist_ok=True)

        pdf_dir = os.path.join(output_dir, "_pdf")
        os.makedirs(pdf_dir, exist_ok=True)

        logger.info("Converting PPTX to PDF: %s", pptx_path)
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                pdf_dir,
                pptx_path,
            ],
            check=True,
            capture_output=True,
        )

        pdf_name = Path(pptx_path).stem + ".pdf"
        pdf_path = os.path.join(pdf_dir, pdf_name)

        logger.info("Rasterizing PDF with ffmpeg/pdftoppm: %s", pdf_path)
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "150",
                pdf_path,
                os.path.join(output_dir, "slide"),
            ],
            check=True,
            capture_output=True,
        )

        images = sorted(
            str(p) for p in Path(output_dir).glob("slide-*.png")
        )
        if not images:
            raise RuntimeError(f"No slides produced from {pptx_path}")
        return images

    def build_video(
        self, image_paths: list[str], audio_paths: list[str], output_path: str
    ) -> str:
        if len(image_paths) != len(audio_paths):
            raise ValueError(
                f"Image/audio count mismatch: {len(image_paths)} vs {len(audio_paths)}"
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        work_dir = Path(output_path).parent
        segment_paths: list[str] = []

        for idx, (img, aud) in enumerate(zip(image_paths, audio_paths)):
            seg_path = str(work_dir / f"_seg_{idx:04d}.mp4")
            logger.info("Building segment %d", idx)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    img,
                    "-i",
                    aud,
                    "-c:v",
                    "libx264",
                    "-tune",
                    "stillimage",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-pix_fmt",
                    "yuv420p",
                    "-shortest",
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    seg_path,
                ],
                check=True,
                capture_output=True,
            )
            segment_paths.append(seg_path)

        list_file = work_dir / "_concat.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in segment_paths:
                f.write(f"file '{seg}'\n")

        logger.info("Concatenating %d segments → %s", len(segment_paths), output_path)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )

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
