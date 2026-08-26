"""migration_guard: flag non-additive Alembic revisions before a live deploy.

Pure filesystem + regex work, so every case builds a throwaway versions/ tree in
tmp_path rather than leaning on the repo's real migration history.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.scripts.migration_guard import ChainError, check, main, pending_revisions

pytestmark = pytest.mark.unit


def _revision(
    versions_dir: Path,
    revision: str,
    down: str | None,
    upgrade_body: str = "    pass",
    downgrade_body: str = "    pass",
) -> Path:
    down_literal = f'"{down}"' if down else "None"
    path = versions_dir / f"{revision}_test.py"
    path.write_text(
        f'"""test revision {revision}."""\n\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n\n"
        f'revision: str = "{revision}"\n'
        f"down_revision: str | None = {down_literal}\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade_body}\n\n\n"
        "def downgrade() -> None:\n"
        f"{downgrade_body}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def versions(tmp_path: Path) -> Path:
    d = tmp_path / "versions"
    d.mkdir()
    return d


# ── chain resolution ─────────────────────────────────────────────────────────


def test_pending_is_ordered_oldest_first(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa")
    _revision(versions, "ccc", "bbb")

    assert [rev for rev, _ in pending_revisions(versions, "aaa", "ccc")] == ["bbb", "ccc"]


def test_empty_current_means_every_revision_is_pending(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa")

    assert [rev for rev, _ in pending_revisions(versions, "", "bbb")] == ["aaa", "bbb"]


def test_current_equal_to_head_has_nothing_pending(versions: Path) -> None:
    _revision(versions, "aaa", None)

    assert pending_revisions(versions, "aaa", "aaa") == []


def test_merge_revision_walks_both_parents(versions: Path) -> None:
    _revision(versions, "root", None)
    _revision(versions, "left", "root")
    _revision(versions, "right", "root")
    path = versions / "merge_test.py"
    path.write_text(
        '"""merge."""\n\nfrom alembic import op\n\n'
        'revision: str = "merge"\n'
        'down_revision = ("left", "right")\n\n'
        "def upgrade() -> None:\n    pass\n\n\n"
        "def downgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )

    pending = {rev for rev, _ in pending_revisions(versions, "root", "merge")}
    assert pending == {"left", "right", "merge"}


def test_unknown_head_is_a_chain_error(versions: Path) -> None:
    _revision(versions, "aaa", None)

    with pytest.raises(ChainError, match="head revision"):
        pending_revisions(versions, "", "nope")


def test_current_on_an_unrelated_branch_is_a_chain_error(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa")
    _revision(versions, "orphan", None)

    with pytest.raises(ChainError, match="not an ancestor"):
        pending_revisions(versions, "orphan", "bbb")


def test_missing_down_revision_is_a_chain_error(versions: Path) -> None:
    _revision(versions, "aaa", "vanished")

    with pytest.raises(ChainError, match="missing down_revision"):
        pending_revisions(versions, "", "aaa")


# ── destructive-operation detection ──────────────────────────────────────────


def test_additive_migration_is_clean(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body=(
            '    op.add_column("lessons", sa.Column("note", sa.String(), nullable=True))\n'
            '    op.create_index("ix_lessons_note", "lessons", ["note"])\n'
            '    op.create_table("widgets", sa.Column("id", sa.Integer(), primary_key=True))'
        ),
    )

    assert check(versions, "aaa", "bbb") == []


@pytest.mark.parametrize(
    ("body", "operation"),
    [
        ('    op.drop_column("lessons", "note")', "op.drop_column()"),
        ('    op.drop_table("widgets")', "op.drop_table()"),
        ('    op.rename_table("widgets", "gadgets")', "op.rename_table()"),
    ],
)
def test_always_destructive_calls_are_flagged(versions: Path, body: str, operation: str) -> None:
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa", upgrade_body=body)

    findings = check(versions, "aaa", "bbb")
    assert [f.operation for f in findings] == [operation]
    assert findings[0].revision == "bbb"


def test_alter_column_to_not_null_is_flagged(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body=(
            '    op.alter_column(\n        "lessons",\n        "note",\n'
            "        existing_type=sa.String(),\n        nullable=False,\n    )"
        ),
    )

    findings = check(versions, "aaa", "bbb")
    assert [f.operation for f in findings] == ["op.alter_column(nullable=False)"]


def test_alter_column_rename_is_flagged(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body='    op.alter_column("lessons", "note", new_column_name="remark")',
    )

    findings = check(versions, "aaa", "bbb")
    assert [f.operation for f in findings] == ["op.alter_column(new_column_name=...)"]


def test_alter_column_widening_is_not_flagged(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body=(
            '    op.alter_column(\n        "lessons",\n        "note",\n'
            "        existing_type=sa.String(64),\n        type_=sa.String(255),\n"
            "        existing_nullable=True,\n    )"
        ),
    )

    assert check(versions, "aaa", "bbb") == []


def test_raw_sql_drop_is_flagged(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body='    op.execute("ALTER TABLE lessons DROP COLUMN note")',
    )

    findings = check(versions, "aaa", "bbb")
    assert findings[0].operation == "op.execute(... DROP COLUMN ...)"


def test_raw_sql_enum_add_value_is_not_flagged(versions: Path) -> None:
    # Hand-written ALTER TYPE ... ADD VALUE is the project's normal way to add an
    # enum member (autogenerate misses them) and is purely additive.
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body="    op.execute(\"ALTER TYPE lessonstatus ADD VALUE 'archived'\")",
    )

    assert check(versions, "aaa", "bbb") == []


def test_downgrade_body_is_ignored(versions: Path) -> None:
    # Every migration's downgrade() drops what upgrade() created; the deploy
    # never runs it, so scanning it would flag the entire history.
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body='    op.add_column("lessons", sa.Column("note", sa.String(), nullable=True))',
        downgrade_body='    op.drop_column("lessons", "note")',
    )

    assert check(versions, "aaa", "bbb") == []


def test_findings_point_at_the_offending_line(versions: Path) -> None:
    _revision(
        versions,
        "aaa",
        None,
        upgrade_body=(
            '    op.add_column("t", sa.Column("c", sa.Integer()))\n    op.drop_table("old")'
        ),
    )

    findings = check(versions, "", "aaa")
    source_lines = (versions / "aaa_test.py").read_text(encoding="utf-8").splitlines()
    assert "op.drop_table" in source_lines[findings[0].line - 1]


# ── CLI contract consumed by deploy/deploy.sh ────────────────────────────────


def test_main_returns_zero_when_additive(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(
        versions,
        "bbb",
        "aaa",
        upgrade_body='    op.add_column("t", sa.Column("c", sa.Integer(), nullable=True))',
    )

    assert main(["--current", "aaa", "--head", "bbb", "--versions-dir", str(versions)]) == 0


def test_main_returns_three_when_destructive(versions: Path) -> None:
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa", upgrade_body='    op.drop_column("t", "c")')

    assert main(["--current", "aaa", "--head", "bbb", "--versions-dir", str(versions)]) == 3


def test_main_returns_one_on_a_broken_chain(versions: Path) -> None:
    _revision(versions, "aaa", None)

    assert main(["--current", "", "--head", "missing", "--versions-dir", str(versions)]) == 1


def test_main_tolerates_whitespace_from_alembic_output(versions: Path) -> None:
    # deploy.sh pipes `alembic current` through awk; a stray newline must not
    # turn into an unknown-revision error.
    _revision(versions, "aaa", None)
    _revision(versions, "bbb", "aaa")

    assert main(["--current", " aaa \n", "--head", " bbb ", "--versions-dir", str(versions)]) == 0


def test_repo_migration_history_is_additive() -> None:
    # Guards the guard: if this ever fails, either a destructive migration landed
    # or the detector started producing false positives on real files.
    from app.scripts.migration_guard import DEFAULT_VERSIONS_DIR, _index

    index = _index(DEFAULT_VERSIONS_DIR)
    children = {parent for _, parents in index.values() for parent in parents}
    heads = [rev for rev in index if rev not in children]
    assert len(heads) == 1, f"expected a single head, got {heads}"

    assert check(DEFAULT_VERSIONS_DIR, "", heads[0]) == []
