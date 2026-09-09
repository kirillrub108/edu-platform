"""Roster import parser: format sniffing, column detection, normalization.

Pure functions only — the DB-writing half lives in tests/integration.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.services.roster_import_service import (
    RosterImportError,
    normalize_email,
    parse_grid,
    select_column,
    validate_email,
)

pytestmark = pytest.mark.unit


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _emails(grid: list[list[str]], explicit: int | None = None) -> list[str | None]:
    selection = select_column(grid, explicit)
    assert selection.index is not None
    body = grid[1:] if selection.skip_first_row else grid
    return [
        validate_email(row[selection.index])
        for row in body
        if selection.index < len(row) and row[selection.index].strip()
    ]


# ── Format parsing ──────────────────────────────────────────────────────────


def test_xlsx_with_header_picks_the_email_column():
    content = _xlsx(
        [
            ["ФИО", "Группа", "Email"],
            ["Иванов И.И.", "БИ-21", "ivanov@example.com"],
            ["Петров П.П.", "БИ-21", "petrov@example.com"],
        ]
    )
    grid = parse_grid("roster.xlsx", content)
    selection = select_column(grid, None)
    assert selection.index == 2
    assert selection.header == "Email"
    assert selection.skip_first_row is True
    assert _emails(grid) == ["ivanov@example.com", "petrov@example.com"]


def test_xlsx_single_column_without_header_treats_first_row_as_data():
    grid = parse_grid("roster.xlsx", _xlsx([["a@example.com"], ["b@example.com"]]))
    selection = select_column(grid, None)
    assert selection.index == 0
    assert selection.skip_first_row is False
    assert _emails(grid) == ["a@example.com", "b@example.com"]


def test_csv_cp1251_semicolon_from_russian_excel():
    content = "ФИО;Email;Группа\r\nИванов;ivanov@example.com;БИ-21\r\n".encode("cp1251")
    grid = parse_grid("список.csv", content)
    assert grid[0][0] == "ФИО"  # Cyrillic survived the decode
    selection = select_column(grid, None)
    assert selection.index == 1
    assert _emails(grid) == ["ivanov@example.com"]


def test_csv_utf8_comma():
    content = "email,name\na@example.com,A\nb@example.com,B\n".encode("utf-8")
    grid = parse_grid("roster.csv", content)
    assert _emails(grid) == ["a@example.com", "b@example.com"]


def test_pdf_renamed_to_csv_is_rejected():
    with pytest.raises(RosterImportError):
        parse_grid("roster.csv", b"%PDF-1.7\n1 0 obj\n")


def test_unknown_extension_is_rejected():
    with pytest.raises(RosterImportError):
        parse_grid("roster.txt", b"a@example.com\n")


def test_broken_xlsx_is_rejected():
    with pytest.raises(RosterImportError):
        parse_grid("roster.xlsx", b"PK\x03\x04not-a-real-workbook")


def test_row_limit_reports_the_actual_count(monkeypatch):
    monkeypatch.setattr("app.services.roster_import_service.ROSTER_IMPORT_MAX_ROWS", 2)
    content = "\n".join(f"u{i}@example.com" for i in range(5)).encode("utf-8")
    with pytest.raises(RosterImportError) as exc:
        parse_grid("roster.csv", content)
    assert "5" in str(exc.value)


# ── Column detection ────────────────────────────────────────────────────────


def test_two_email_columns_ask_for_a_choice():
    grid = parse_grid(
        "roster.csv",
        "Личная;Рабочая\na@example.com;a@work.com\nb@example.com;b@work.com\n".encode("utf-8"),
    )
    selection = select_column(grid, None)
    assert selection.index is None
    assert [c.header for c in selection.options] == ["Личная", "Рабочая"]
    assert selection.options[0].samples == ["a@example.com", "b@example.com"]


def test_explicit_column_overrides_detection():
    grid = parse_grid(
        "roster.csv",
        "Личная;Рабочая\na@example.com;a@work.com\n".encode("utf-8"),
    )
    assert _emails(grid, explicit=1) == ["a@work.com"]


def test_explicit_column_out_of_range_is_rejected():
    grid = parse_grid("roster.csv", "a@example.com\n".encode("utf-8"))
    with pytest.raises(RosterImportError):
        select_column(grid, 7)


def test_no_email_column_at_all_asks_for_a_choice():
    grid = parse_grid("roster.csv", "ФИО;Группа\nИванов;БИ-21\n".encode("utf-8"))
    assert select_column(grid, None).index is None


def test_garbage_and_empty_cells_do_not_break_the_column():
    grid = parse_grid(
        "roster.csv",
        "email\na@example.com\n—\n\nнет\nИванов И.И.\nb@example.com\n".encode("utf-8"),
    )
    assert _emails(grid) == ["a@example.com", None, None, None, "b@example.com"]


# ── Normalization ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Имя Фамилия <Mail@Example.RU>", "mail@example.ru"),
        ("  spaced@example.com  ", "spaced@example.com"),
        ("UPPER@EXAMPLE.COM", "upper@example.com"),
        ("mailto:link@example.com", "link@example.com"),
        ("\u00a0nbsp@example.com\u00a0", "nbsp@example.com"),
        ("\u200bzero@example.com\ufeff", "zero@example.com"),
        ('"quoted@example.com"', "quoted@example.com"),
    ],
)
def test_normalize_email(raw: str, expected: str):
    assert normalize_email(raw) == expected


def test_nbsp_around_address_is_folded_away():
    assert validate_email("\u00a0user@example.com\u00a0") == "user@example.com"


def test_invalid_addresses_are_rejected():
    for raw in ("—", "нет", "Иванов И.И.", "user@", "@example.com", ""):
        assert validate_email(raw) is None
