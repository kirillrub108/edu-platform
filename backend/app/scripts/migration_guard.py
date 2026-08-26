"""Refuse to deploy a schema change that the previous release cannot survive.

Zero-downtime rollout means both releases run against the same database for the
length of the switch, so a migration must follow expand/contract: release N only
ADDS (nullable columns, new tables, indexes), and the drops/renames that release
N-1 would choke on wait for release N+1. See docs/DECISIONS.md §53.

This scans the revisions between the database's current head and the target head
for the operations that break that rule, and reports them. It never touches the
database — the two revision ids are passed in by deploy/deploy.sh, which reads
them from `alembic current` / `alembic heads`.

    python -m app.scripts.migration_guard --current <rev> --head <rev>

Exit codes: 0 = additive only, 3 = destructive operations found, 1 = the
revision chain could not be resolved (treat as unsafe — deploy.sh does).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# Alembic writes `revision: str = "abc"` in current templates and plain
# `revision = 'abc'` in older ones; accept both.
_REVISION_RE = re.compile(
    r"^revision(?:\s*:\s*[^=]+)?\s*=\s*(?P<value>.+)$",
    re.MULTILINE,
)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?P<value>.+)$",
    re.MULTILINE,
)
_STRING_RE = re.compile(r"""['"]([^'"]+)['"]""")

# Bare `op.<name>(` calls that are destructive whatever their arguments.
_ALWAYS_DESTRUCTIVE: dict[str, str] = {
    "drop_column": "drops a column the previous release still writes",
    "drop_table": "drops a table the previous release still reads",
    "rename_table": "renames a table out from under the previous release",
}

# Raw SQL is opaque to the checks above, so look inside op.execute() too.
_RAW_SQL_RE = re.compile(
    r"\b(DROP\s+COLUMN|DROP\s+TABLE|RENAME\s+COLUMN|RENAME\s+TO)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    """One destructive operation, located precisely enough to fix."""

    revision: str
    file: str
    line: int
    operation: str
    reason: str

    def render(self) -> str:
        return f"  {self.file}:{self.line}  {self.operation} — {self.reason}"


class ChainError(RuntimeError):
    """The revision graph could not be walked from head down to current."""


def _first_string(value: str) -> str | None:
    match = _STRING_RE.search(value)
    return match.group(1) if match else None


def _all_strings(value: str) -> tuple[str, ...]:
    return tuple(_STRING_RE.findall(value))


def parse_revision(path: Path) -> tuple[str, tuple[str, ...]]:
    """Return (revision, parents) for one migration file.

    `down_revision` may be None (base), a string, or a tuple of strings for a
    merge revision — all three collapse into the parents tuple.
    """
    source = path.read_text(encoding="utf-8")

    revision_match = _REVISION_RE.search(source)
    if revision_match is None:
        raise ChainError(f"{path.name}: no `revision = ...` assignment")
    revision = _first_string(revision_match.group("value"))
    if revision is None:
        raise ChainError(f"{path.name}: `revision` is not a string literal")

    down_match = _DOWN_REVISION_RE.search(source)
    parents = _all_strings(down_match.group("value")) if down_match else ()
    return revision, parents


def _index(versions_dir: Path) -> dict[str, tuple[Path, tuple[str, ...]]]:
    index: dict[str, tuple[Path, tuple[str, ...]]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        revision, parents = parse_revision(path)
        if revision in index:
            raise ChainError(f"duplicate revision id {revision!r} in {versions_dir}")
        index[revision] = (path, parents)
    return index


def pending_revisions(versions_dir: Path, current: str, head: str) -> list[tuple[str, Path]]:
    """Revisions strictly between `current` (exclusive) and `head` (inclusive).

    An empty `current` means an empty database — every revision is pending.
    Ordered oldest-first so findings read in the order they would be applied.
    """
    index = _index(versions_dir)
    if head not in index:
        raise ChainError(f"head revision {head!r} not found in {versions_dir}")
    if current and current not in index:
        raise ChainError(
            f"current revision {current!r} not found in {versions_dir} — "
            "the database is on a revision this checkout does not contain"
        )
    if current == head:
        return []

    collected: list[tuple[str, Path]] = []
    seen: set[str] = set()
    reached_current = not current
    frontier: list[str] = [head]
    while frontier:
        revision = frontier.pop()
        if revision in seen:
            continue
        if revision == current:
            reached_current = True
            continue
        seen.add(revision)
        path, parents = index[revision]
        collected.append((revision, path))
        for parent in parents:
            if parent not in index:
                raise ChainError(
                    f"revision {revision!r} points at missing down_revision {parent!r}"
                )
            frontier.append(parent)

    if not reached_current:
        # Walking down from head never passed through `current`: the two sit on
        # unrelated branches and "what is pending" has no answer.
        raise ChainError(f"current revision {current!r} is not an ancestor of head {head!r}")

    collected.reverse()
    return collected


def _call_source(source: str, open_paren: int) -> str:
    """Slice one balanced call expression starting at its opening paren."""
    depth = 0
    quote: str | None = None
    for offset in range(open_paren, len(source)):
        char = source[offset]
        if quote is not None:
            if char == quote and source[offset - 1] != "\\":
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren : offset + 1]
    return source[open_paren:]


def _upgrade_body(source: str) -> tuple[int, int]:
    """Offsets of the `upgrade()` body — everything up to the next top-level def.

    Only `upgrade()` matters here: `downgrade()` drops whatever `upgrade()`
    created by definition, and the deploy never runs it. Scanning the whole file
    would flag every migration ever written.
    """
    start_match = re.search(r"^def upgrade\s*\(", source, re.MULTILINE)
    if start_match is None:
        return 0, 0
    start = start_match.end()
    end_match = re.compile(r"^def ", re.MULTILINE).search(source, start)
    return start, end_match.start() if end_match else len(source)


def scan_file(revision: str, path: Path) -> list[Finding]:
    """Find every destructive operation in one migration file's `upgrade()`."""
    source = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    body_start, body_end = _upgrade_body(source)

    def line_of(offset: int) -> int:
        return source.count("\n", 0, offset) + 1

    for match in re.finditer(r"\bop\.(\w+)\s*\(", source[body_start:body_end]):
        name = match.group(1)
        open_paren = body_start + match.end() - 1
        line = line_of(body_start + match.start())

        reason = _ALWAYS_DESTRUCTIVE.get(name)
        if reason is not None:
            findings.append(Finding(revision, path.name, line, f"op.{name}()", reason))
            continue

        if name == "alter_column":
            args = _call_source(source, open_paren)
            if "new_column_name" in args:
                findings.append(
                    Finding(
                        revision,
                        path.name,
                        line,
                        "op.alter_column(new_column_name=...)",
                        "renames a column the previous release still writes",
                    )
                )
            if re.search(r"nullable\s*=\s*False", args):
                findings.append(
                    Finding(
                        revision,
                        path.name,
                        line,
                        "op.alter_column(nullable=False)",
                        "the previous release still inserts rows without this column",
                    )
                )
            continue

        if name == "execute":
            args = _call_source(source, open_paren)
            sql = _RAW_SQL_RE.search(args)
            if sql is not None:
                findings.append(
                    Finding(
                        revision,
                        path.name,
                        line,
                        f"op.execute(... {sql.group(1).upper()} ...)",
                        "raw SQL that drops or renames schema objects",
                    )
                )

    return findings


def check(versions_dir: Path, current: str, head: str) -> list[Finding]:
    findings: list[Finding] = []
    for revision, path in pending_revisions(versions_dir, current, head):
        findings.extend(scan_file(revision, path))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migration_guard",
        description="Flag non-additive Alembic revisions before a zero-downtime deploy.",
    )
    parser.add_argument("--current", default="", help="revision the database is on (may be empty)")
    parser.add_argument("--head", required=True, help="revision the deploy would upgrade to")
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=DEFAULT_VERSIONS_DIR,
        help=f"alembic versions directory (default: {DEFAULT_VERSIONS_DIR})",
    )
    args = parser.parse_args(argv)

    try:
        findings = check(args.versions_dir, args.current.strip(), args.head.strip())
    except ChainError as exc:
        print(f"migration_guard: cannot resolve the revision chain: {exc}", file=sys.stderr)
        return 1

    if not findings:
        print("migration_guard: pending migrations are additive — safe to deploy live.")
        return 0

    print("migration_guard: DESTRUCTIVE operations found in pending migrations:")
    for finding in findings:
        print(finding.render())
    print(
        "\nThese break the previous release while both versions serve traffic.\n"
        "Split them into a follow-up release (expand now, contract next), or set\n"
        "DEPLOY_ALLOW_UNSAFE_MIGRATION=1 to deploy behind the maintenance page."
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
