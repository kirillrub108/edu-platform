"""Unit tests for the file-deletion helpers of app.tasks.purge_pipeline.

Purge is the one place that deletes user data for good, so the properties
pinned here are: every artifact kind of a lesson is actually removed (a missed
one leaks paid content and disk), and no single failure — a vanished file, an
unreadable entry, a storage outage — aborts the run and strands the rest.

The DB is a mocked sync Session (tasks are prefork/sync by contract) and
storage is a recording fake; the disk-cache tests use tmp_path. Retention and
GC *policy* is covered in tests/integration/test_cache_gc.py and
test_soft_delete.py — this file covers the resilience branches around it.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def pp() -> ModuleType:
    """Import the task module lazily.

    `app.tasks.purge_pipeline` does `from ...video_pipeline import SyncSession`,
    and conftest rebinds that sessionmaker only once the Postgres container is
    up. Importing at collection time would freeze the placeholder engine into
    the module and break every other test that uses it.
    """
    from app.tasks import purge_pipeline

    return purge_pipeline


class _FakeStorage:
    """Records deletions; `missing` marks paths that report exists()=False and
    `failing` marks paths whose deletion raises."""

    def __init__(
        self,
        module: ModuleType,
        missing: set[str] | None = None,
        failing: set[str] | None = None,
    ) -> None:
        self._pp = module
        self.deleted: list[str] = []
        self.prefixes: list[str] = []
        self.missing = missing or set()
        self.failing = failing or set()

    def exists(self, path: str) -> bool:
        return path not in self.missing

    def delete_file(self, path: str) -> None:
        if path in self.failing:
            raise OSError(f"storage down for {path}")
        self.deleted.append(path)

    def delete_prefix(self, prefix: str) -> None:
        if prefix in self.failing:
            raise OSError(f"storage down for {prefix}")
        self.prefixes.append(prefix)

    def relative_path_from_url(self, url: str | None) -> str | None:
        return self._pp._rel_from_url(url)


@pytest.fixture()
def storage(pp: ModuleType, monkeypatch: pytest.MonkeyPatch) -> _FakeStorage:
    fake = _FakeStorage(pp)
    monkeypatch.setattr(pp, "storage_service", fake)
    return fake


def _session_returning(*batches: list[Any]) -> MagicMock:
    """Mock Session whose successive .execute().scalars().all() calls return
    the given batches in order."""
    queue = list(batches)
    session = MagicMock()

    def _execute(*_args: Any, **_kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = queue.pop(0)
        return result

    session.execute.side_effect = _execute
    return session


# ── _rel_from_url ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [None, "", "https://cdn.example.com/media/x.mp4"])
def test_rel_from_url_returns_none_for_non_local_urls(pp: ModuleType, url: str | None) -> None:
    assert pp._rel_from_url(url) is None


def test_rel_from_url_strips_signature_and_decodes_the_path(pp: ModuleType) -> None:
    url = "http://localhost:8000/files/videos/abc/lesson%20one.mp4?exp=123&sig=deadbeef"
    assert pp._rel_from_url(url) == "videos/abc/lesson one.mp4"


# ── _remove_file / _remove_lesson_dirs ────────────────────────────────────────


def test_remove_file_ignores_empty_path(pp: ModuleType, storage: _FakeStorage) -> None:
    pp._remove_file(None)
    pp._remove_file("")
    assert storage.deleted == []


def test_remove_file_deletes_an_existing_path(pp: ModuleType, storage: _FakeStorage) -> None:
    pp._remove_file("videos/a/b.mp4")
    assert storage.deleted == ["videos/a/b.mp4"]


def test_remove_file_tolerates_an_already_gone_file(
    pp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeStorage(pp, missing={"videos/a/b.mp4"})
    monkeypatch.setattr(pp, "storage_service", fake)

    pp._remove_file("videos/a/b.mp4")

    assert fake.deleted == []  # nothing to delete, and no exception


def test_remove_file_swallows_a_storage_outage(
    pp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One unreachable object must not abort the whole purge run."""
    fake = _FakeStorage(pp, failing={"videos/a/b.mp4"})
    monkeypatch.setattr(pp, "storage_service", fake)

    pp._remove_file("videos/a/b.mp4")

    assert fake.deleted == []


def test_remove_lesson_dirs_tries_both_prefixes_even_if_one_fails(
    pp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    lesson_id = uuid.uuid4()
    fake = _FakeStorage(pp, failing={f"videos/{lesson_id}"})
    monkeypatch.setattr(pp, "storage_service", fake)

    pp._remove_lesson_dirs(lesson_id)

    assert fake.prefixes == [f"lessons/{lesson_id}"]


# ── _purge_assignment_files ───────────────────────────────────────────────────


def test_purge_assignment_files_skips_the_second_query_without_submissions(
    pp: ModuleType, storage: _FakeStorage
) -> None:
    session = _session_returning([])

    pp._purge_assignment_files(session, SimpleNamespace(id=uuid.uuid4()))

    assert session.execute.call_count == 1
    assert storage.prefixes == []


def test_purge_assignment_files_removes_attachments_and_submission_dirs(
    pp: ModuleType, storage: _FakeStorage
) -> None:
    sid1, sid2 = uuid.uuid4(), uuid.uuid4()
    session = _session_returning(
        [sid1, sid2],
        ["assignments/a/report.pdf", "assignments/b/notes.docx"],
    )

    pp._purge_assignment_files(session, SimpleNamespace(id=uuid.uuid4()))

    assert storage.deleted == ["assignments/a/report.pdf", "assignments/b/notes.docx"]
    assert storage.prefixes == [f"assignments/{sid1}", f"assignments/{sid2}"]


# ── _purge_lesson_files ───────────────────────────────────────────────────────


def test_purge_lesson_files_removes_every_artifact_kind(
    pp: ModuleType, storage: _FakeStorage
) -> None:
    lesson_id = uuid.uuid4()
    lesson = SimpleNamespace(
        id=lesson_id,
        video_url=f"http://localhost:8000/files/videos/{lesson_id}/final.mp4?sig=x",
        pptx_path=f"lessons/{lesson_id}/source.pptx",
    )
    session = _session_returning(
        [SimpleNamespace(video_url=f"http://localhost:8000/files/videos/{lesson_id}/v1.mp4")],
        [SimpleNamespace(image_path=f"lessons/{lesson_id}/slides/slide_0001.png")],
        [],  # no assignment submissions
    )

    pp._purge_lesson_files(session, lesson)

    assert storage.deleted == [
        f"videos/{lesson_id}/final.mp4",
        f"lessons/{lesson_id}/source.pptx",
        f"videos/{lesson_id}/v1.mp4",
        f"lessons/{lesson_id}/slides/slide_0001.png",
    ]
    assert storage.prefixes == [f"videos/{lesson_id}", f"lessons/{lesson_id}"]


# ── _purge_course_files / _purge_user_files ───────────────────────────────────


def test_purge_course_files_removes_cover_and_fans_out_to_lessons(
    pp: ModuleType, storage: _FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(pp, "_purge_lesson_files", lambda _s, lesson: seen.append(lesson))
    lessons = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    session = _session_returning(lessons)
    course = SimpleNamespace(
        id=uuid.uuid4(), cover_url="http://localhost:8000/files/covers/c.png?sig=x"
    )

    pp._purge_course_files(session, course)

    assert storage.deleted == ["covers/c.png"]
    assert seen == lessons


def test_purge_user_files_fans_out_to_every_owned_course(
    pp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Courses cascade-delete with the user, so their files must go first."""
    seen: list[Any] = []
    monkeypatch.setattr(pp, "_purge_course_files", lambda _s, course: seen.append(course))
    courses = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    session = _session_returning(courses)

    pp._purge_user_files(session, SimpleNamespace(id=uuid.uuid4()))

    assert seen == courses


# ── disk-cache GC resilience ──────────────────────────────────────────────────


def _entry(root: Path, name: str, *, size: int = 16) -> Path:
    path = root / name
    path.mkdir()
    (path / "data.bin").write_bytes(b"0" * size)
    return path


def test_entry_size_treats_a_vanished_file_as_zero(pp: ModuleType, tmp_path: Path) -> None:
    assert pp._entry_size(str(tmp_path / "gone.txt"), False) == 0


def test_entry_size_sums_a_directory_tree(pp: ModuleType, tmp_path: Path) -> None:
    entry = _entry(tmp_path, "hash1", size=32)
    (entry / "nested").mkdir()
    (entry / "nested" / "more.bin").write_bytes(b"0" * 8)

    assert pp._entry_size(str(entry), True) == 40


def test_gc_clears_orphans_left_by_a_crashed_run(pp: ModuleType, tmp_path: Path) -> None:
    """A half-renamed staging entry is not a cache hit — it must be reaped."""
    orphan = _entry(tmp_path, f"hash1{pp._GC_STAGING_MARKER}abcdef")
    fresh = _entry(tmp_path, "hash2")

    pp._gc_cache(str(tmp_path), ttl_days=30, max_bytes=10**9, entry_is_dir=True)

    assert not orphan.exists()
    assert fresh.exists()


def test_gc_never_follows_a_symlink(pp: ModuleType, tmp_path: Path) -> None:
    """Deleting through a link would take out the target, not the cache entry."""
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.bin").write_bytes(b"data")
    cache = tmp_path / "cache"
    cache.mkdir()
    link = cache / "hash1"
    link.symlink_to(outside, target_is_directory=True)
    os.utime(outside, (0, 0))

    removed, _freed = pp._gc_cache(str(cache), ttl_days=1, max_bytes=0, entry_is_dir=True)

    assert removed == 0
    assert (outside / "keep.bin").exists()


def test_gc_skips_entries_of_the_wrong_kind(pp: ModuleType, tmp_path: Path) -> None:
    stray_file = tmp_path / "stray.log"
    stray_file.write_bytes(b"0" * 64)
    os.utime(stray_file, (0, 0))
    stale_dir = _entry(tmp_path, "hash1")
    os.utime(stale_dir, (0, 0))

    removed, _freed = pp._gc_cache(str(tmp_path), ttl_days=1, max_bytes=10**9, entry_is_dir=True)

    assert removed == 1
    assert stray_file.exists()  # dir-mode GC leaves files alone


def test_gc_summaries_mode_only_touches_txt_files(pp: ModuleType, tmp_path: Path) -> None:
    stale_txt = tmp_path / "hash1.txt"
    stale_txt.write_text("summary", encoding="utf-8")
    other = tmp_path / "hash2.json"
    other.write_text("{}", encoding="utf-8")
    for p in (stale_txt, other):
        os.utime(p, (0, 0))

    removed, _freed = pp._gc_cache(str(tmp_path), ttl_days=1, max_bytes=10**9, entry_is_dir=False)

    assert removed == 1
    assert not stale_txt.exists()
    assert other.exists()


def test_gc_keeps_an_entry_it_failed_to_evict(
    pp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked entry stays a survivor instead of being counted as freed."""
    stale = _entry(tmp_path, "hash1")
    os.utime(stale, (0, 0))
    monkeypatch.setattr(pp.os, "rename", MagicMock(side_effect=OSError("busy")))

    removed, freed = pp._gc_cache(str(tmp_path), ttl_days=1, max_bytes=0, entry_is_dir=True)

    assert (removed, freed) == (0, 0)
    assert stale.exists()


def test_gc_returns_zero_for_a_missing_cache_root(pp: ModuleType, tmp_path: Path) -> None:
    assert pp._gc_cache(str(tmp_path / "nope"), 30, 10**9, entry_is_dir=True) == (0, 0)


# ── lesson-video eviction ─────────────────────────────────────────────────────


def test_evict_lesson_video_deletes_the_row_when_the_url_is_unresolvable(
    pp: ModuleType, storage: _FakeStorage
) -> None:
    session = MagicMock()
    video = SimpleNamespace(id=uuid.uuid4(), video_url="s3://elsewhere/v.mp4")

    pp._evict_lesson_video(session, video)

    assert storage.deleted == []
    session.delete.assert_called_once_with(video)
    assert session.flush.called


def test_evict_lesson_video_deletes_the_row_even_if_the_file_delete_fails(
    pp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File first, row second — but a storage error must not strand the row."""
    fake = _FakeStorage(pp, failing={"videos/l1/v.mp4"})
    monkeypatch.setattr(pp, "storage_service", fake)
    session = MagicMock()
    video = SimpleNamespace(id=uuid.uuid4(), video_url="http://x/files/videos/l1/v.mp4")

    pp._evict_lesson_video(session, video)

    session.delete.assert_called_once_with(video)


def test_video_gc_rolls_back_and_continues_after_a_failed_lesson(pp: ModuleType) -> None:
    session = _session_returning([uuid.uuid4(), uuid.uuid4()])
    session.scalar.side_effect = RuntimeError("db hiccup")

    assert pp._gc_lesson_videos_session(session) == 0
    assert session.rollback.call_count == 2
