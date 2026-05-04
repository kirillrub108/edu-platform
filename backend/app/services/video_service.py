import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pptx import Presentation

# Bundled LibreOffice font-substitution profile; maps Windows/macOS emoji fonts
# (Segoe UI Emoji, Apple Color Emoji) to Noto Color Emoji which is installed in
# the container. Must be copied into the per-run UserInstallation directory so
# LibreOffice picks it up (the -env:UserInstallation flag overrides the default
# ~/.config/libreoffice path, making any static home-dir config irrelevant).
_LO_XCU_SRC = Path(__file__).parent.parent.parent / "lo-emoji-substitution.xcu"

# 150 DPI is indistinguishable from 300 DPI on a 1080p screen but produces
# 4× smaller PNG files and cuts pdftoppm + FFmpeg encoding time significantly.
_SLIDE_DPI = 150

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd[:4])}\n{stderr}"
        )


def _slide_number(path: str) -> int:
    m = re.findall(r"(\d+)", Path(path).stem)
    return int(m[-1]) if m else 0


def _get_audio_duration(path: str) -> float:
    """Return audio duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(f"ffprobe returned no duration for {path}")
    return float(raw)


def _trim_trailing_silence(src: str, dest: str) -> bool:
    """Write *src* to *dest* with trailing silence removed.

    Threshold: -40 dB, minimum silence run: 0.15 s.
    Returns True when *dest* is valid (≥ 0.1 s) and should be used;
    the caller must fall back to *src* when False is returned.
    """
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-i", src,
            "-af",
            "silenceremove="
            "stop_periods=-1:"
            "stop_duration=0.15:"
            "stop_threshold=-40dB",
            dest,
        ],
        capture_output=True,
        timeout=60,
    )
    if r.returncode != 0:
        logger.warning(
            "silenceremove failed for %s (exit %d), using original",
            src, r.returncode,
        )
        return False
    try:
        dur = _get_audio_duration(dest)
    except (ValueError, RuntimeError, OSError):
        return False
    if dur < 0.1:
        logger.warning(
            "trimmed audio %s is too short (%.3fs), using original", src, dur
        )
        return False
    return True


def _seed_lo_profile(lo_user_dir: str) -> None:
    """Pre-populate LibreOffice UserInstallation with emoji font-substitution config."""
    xcu_dest = Path(lo_user_dir) / "user" / "registrymodifications.xcu"
    xcu_dest.parent.mkdir(parents=True, exist_ok=True)
    if _LO_XCU_SRC.exists():
        shutil.copy2(_LO_XCU_SRC, xcu_dest)
    else:
        logger.warning(
            "lo-emoji-substitution.xcu not found at %s, skipping emoji font config",
            _LO_XCU_SRC,
        )


def _pptx_cache_key(pptx_path: str) -> str:
    """Content hash + DPI → stable key for the PNG slide cache."""
    h = hashlib.md5()
    with open(pptx_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"{h.hexdigest()}_dpi{_SLIDE_DPI}"


class VideoService:
    FRAME_RATE = 25
    # Concurrent FFmpeg processes for segment encoding. 3 on a 4-core machine
    # leaves room for LibreOffice, TTS threads, and the OS.
    _ENCODE_WORKERS = 3

    def extract_slide_texts(self, pptx_path: str) -> list[str]:
        if Path(pptx_path).suffix.lower() not in {".pptx", ".ppt"}:
            logger.info("Skipping text extraction for non-PPTX file: %s", pptx_path)
            return []
        try:
            prs = Presentation(pptx_path)
        except Exception:
            logger.exception("Failed to open PPTX: %s", pptx_path)
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

    def convert_pptx_to_images(
        self,
        pptx_path: str,
        output_dir: str,
        cache_dir: str | None = None,
    ) -> list[str]:
        """Convert PPTX/PDF to a sorted list of PNG slide images.

        When *cache_dir* is provided, results are cached by a hash of the
        source file. Repeat conversions of the same PPTX skip LibreOffice and
        pdftoppm entirely and return the cached PNGs (~20-30s saved per hit).
        """
        suffix = Path(pptx_path).suffix.lower()

        # ── cache lookup (PPTX only — PDFs are read directly, no conversion) ──
        if cache_dir and suffix != ".pdf":
            cache_key = _pptx_cache_key(pptx_path)
            cached_dir = os.path.join(cache_dir, cache_key)
            cached_images = sorted(
                (str(p) for p in Path(cached_dir).glob("slide-*.png")),
                key=_slide_number,
            )
            if cached_images:
                logger.info(
                    "Slide cache hit (%s…) — returning %d cached images",
                    cache_key[:8], len(cached_images),
                )
                return cached_images

        os.makedirs(output_dir, exist_ok=True)

        if suffix == ".pdf":
            # Use the PDF directly — running it through LibreOffice would corrupt
            # embedded fonts (especially Cyrillic), producing garbled text in the output.
            pdf_path = pptx_path
        else:
            pdf_dir = os.path.join(output_dir, "_pdf")
            os.makedirs(pdf_dir, exist_ok=True)

            lo_user_dir = os.path.join(output_dir, "_lo_profile")
            _seed_lo_profile(lo_user_dir)
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

        _run([
            "pdftoppm", "-png", "-r", str(_SLIDE_DPI),
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
        logger.info("Produced %d slide images at %d DPI", len(images), _SLIDE_DPI)

        # ── populate cache ─────────────────────────────────────────────────────
        if cache_dir and suffix != ".pdf":
            os.makedirs(cached_dir, exist_ok=True)
            for img in images:
                shutil.copy2(img, cached_dir)
            logger.info(
                "Cached %d slide images → %s…", len(images), cache_key[:8]
            )

        return images

    def encode_segment(self, idx: int, img: str, aud: str, work_dir: str) -> str:
        """Encode one (image, audio) pair into an MKV segment.

        Thread-safe: all subprocess calls are independent per segment.
        Returns the path to the encoded .mkv file.
        """
        work = Path(work_dir)
        seg_path = str(work / f"_seg_{idx:04d}.mkv")
        trimmed_aud = str(work / f"_aud_{idx:04d}_trim.wav")
        effective_aud = trimmed_aud if _trim_trailing_silence(aud, trimmed_aud) else aud

        duration = _get_audio_duration(effective_aud)
        logger.info("Encoding segment %d (%.2fs)", idx, duration)

        _run([
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(self.FRAME_RATE),
            "-t", str(duration),
            "-i", img,
            "-i", effective_aud,
            # "fast" instead of "medium": ~30% quicker with no visible quality
            # difference for still-image video (tune stillimage suppresses motion
            # estimation anyway, making the preset gap negligible).
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "fast",
            "-r", str(self.FRAME_RATE),
            "-bf", "0",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            seg_path,
        ])
        return seg_path

    def concatenate_segments(self, segment_paths: list[str], output_path: str) -> str:
        """Stream-copy pre-encoded MKV segments into the final MP4 without re-encoding."""
        work_dir = Path(output_path).parent
        os.makedirs(work_dir, exist_ok=True)

        list_path = str(work_dir / "_concat_list.txt")
        with open(list_path, "w") as fh:
            for seg in segment_paths:
                fh.write(f"file '{seg}'\n")

        logger.info("Concatenating %d segments → %s", len(segment_paths), output_path)
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

    def build_video(
        self,
        image_paths: list[str],
        audio_paths: list[str],
        output_path: str,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> str:
        """Encode all segments in parallel then concatenate into the final MP4.

        Uses up to _ENCODE_WORKERS concurrent FFmpeg processes. Progress is
        reported via *progress_cb(done, total)* after each segment completes.
        """
        if len(image_paths) != len(audio_paths):
            raise ValueError(
                f"Image/audio count mismatch: {len(image_paths)} vs {len(audio_paths)}"
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        work_dir = str(Path(output_path).parent)
        total = len(image_paths)
        segment_paths: list[str | None] = [None] * total

        with ThreadPoolExecutor(
            max_workers=self._ENCODE_WORKERS, thread_name_prefix="enc"
        ) as pool:
            futures = {
                pool.submit(self.encode_segment, idx, img, aud, work_dir): idx
                for idx, (img, aud) in enumerate(zip(image_paths, audio_paths))
            }
            for future in as_completed(futures):
                idx = futures[future]
                segment_paths[idx] = future.result()
                if progress_cb:
                    progress_cb(sum(1 for p in segment_paths if p), total)

        return self.concatenate_segments(segment_paths, output_path)  # type: ignore[arg-type]


video_service = VideoService()
