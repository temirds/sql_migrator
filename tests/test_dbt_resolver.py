from __future__ import annotations

from pathlib import Path

from conftest import write_manifest
from dbt_resolver import parse_dwh_stage2_table, resolve_tables


def test_parse_dwh_stage2_table_with_dollar_separator() -> None:
    parsed = parse_dwh_stage2_table("S0090$TRADEPOINT_ONL_HISTORY")

    assert parsed == {
        "source_schema": "S0090",
        "source_table": "TRADEPOINT_ONL_HISTORY",
        "preferred_model": "STG__S0090_TRADEPOINT_ONL_HISTORY",
    }


def test_dwh_stage2_prefers_staging_model(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from DWH_STAGE2.S01#Z_CLIENT",
        str(tmp_path),
        {},
    )

    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in result.sql
    assert result.warnings == []


def test_dwh_stage2_multipart_source_name_resolves_to_staging_model(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from DWH_STAGE2.S01.Z_CLIENT",
        str(tmp_path),
        {},
    )

    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in result.sql
    assert result.warnings == []


def test_physical_model_resolves_to_prod_xref(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from ds_bin_restrictions_p",
        str(tmp_path),
        {},
    )

    assert "{{ xref('DS_BIN_RESTRICTIONS_P', 'PROD') }}" in result.sql
    assert result.warnings == []


def test_dwh_stage2_tradepoint_prefers_staging_model(tmp_path: Path) -> None:
    write_manifest(tmp_path, include_tradepoint_model=True, include_sources=True)

    result = resolve_tables(
        "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
        str(tmp_path),
        {},
    )

    assert "{{ xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE') }}" in result.sql
    assert "{{ source(" not in result.sql
    assert result.warnings == []


def test_dwh_stage2_tradepoint_falls_back_to_source(tmp_path: Path) -> None:
    write_manifest(tmp_path, include_sources=True)

    result = resolve_tables(
        "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
        str(tmp_path),
        {},
    )

    assert "{{ source('S0090', 'TRADEPOINT_ONL_HISTORY') }}" in result.sql
    assert result.warnings == []


def test_dwh_stage2_does_not_use_partial_model_match(tmp_path: Path) -> None:
    write_manifest(tmp_path, include_tradepoint_partial_model=True, include_sources=True)

    result = resolve_tables(
        "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
        str(tmp_path),
        {},
    )

    assert "STG__S0090_TRADEPOINT_ONL'" not in result.sql
    assert "{{ xref('STG__S0090_TRADEPOINT_ONL', 'DWH_STAGE') }}" not in result.sql
    assert "{{ source('S0090', 'TRADEPOINT_ONL_HISTORY') }}" in result.sql


def test_dwh_stage2_unresolved_uses_physical_fallback(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
        str(tmp_path),
        {},
    )

    assert "from S0090.TRADEPOINT_ONL_HISTORY" in result.sql
    assert "dwh_stage2.s0090_tradepoint_onl_history" not in result.sql.lower()
    assert (
        "unresolved table: DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY, "
        "fallback physical: S0090.TRADEPOINT_ONL_HISTORY"
    ) in result.warnings


def test_dwh_stage2_hash_table_prefers_staging_model_then_source(tmp_path: Path) -> None:
    write_manifest(tmp_path, include_sources=True)

    with_model = resolve_tables(
        "select * from DWH_STAGE2.S01#Z_CLIENT",
        str(tmp_path),
        {},
    )

    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in with_model.sql

    write_manifest(tmp_path, include_s01_model=False, include_sources=True)

    without_model = resolve_tables(
        "select * from DWH_STAGE2.S01#Z_CLIENT",
        str(tmp_path),
        {},
    )

    assert "{{ source('S01', 'Z_CLIENT') }}" in without_model.sql


def test_dwh_stage2_unknown_table_is_unresolved(tmp_path: Path) -> None:
    write_manifest(tmp_path, include_sources=True)

    result = resolve_tables(
        "select * from DWH_STAGE2.S0090$UNKNOWN_TABLE",
        str(tmp_path),
        {},
    )

    assert "S0090.UNKNOWN_TABLE" in result.sql
    assert (
        "unresolved table: DWH_STAGE2.S0090$UNKNOWN_TABLE, "
        "fallback physical: S0090.UNKNOWN_TABLE"
    ) in result.warnings


def test_unknown_table_adds_unresolved_warning(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from UNKNOWN_SCHEMA.SOME_TABLE",
        str(tmp_path),
        {},
    )

    assert "UNKNOWN_SCHEMA.SOME_TABLE" in result.sql
    assert "unresolved table: UNKNOWN_SCHEMA.SOME_TABLE" in result.warnings
