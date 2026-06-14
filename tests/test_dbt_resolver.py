from __future__ import annotations

from pathlib import Path

from conftest import write_manifest
from dbt_resolver import resolve_tables


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


def test_unknown_table_adds_unresolved_warning(tmp_path: Path) -> None:
    write_manifest(tmp_path)

    result = resolve_tables(
        "select * from UNKNOWN_SCHEMA.SOME_TABLE",
        str(tmp_path),
        {},
    )

    assert "UNKNOWN_SCHEMA.SOME_TABLE" in result.sql
    assert "unresolved table: UNKNOWN_SCHEMA.SOME_TABLE" in result.warnings
