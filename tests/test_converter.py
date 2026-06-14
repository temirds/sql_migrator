from __future__ import annotations

from pathlib import Path

from conftest import write_manifest
from converter import convert_oracle_to_starrocks
from dbt_resolver import resolve_tables


ORACLE_SQL = """
insert /*+ append */
into other.dm$partners_sales$p1
select
    sysdate as s$change_date,
    standard_hash(t.org_bin, 'MD5') as s$md5,
    nvl(t.org_bin, 'N/A') as org_bin
from DWH_STAGE2.S01#Z_CLIENT t
join UNKNOWN_SCHEMA.SOME_TABLE u on u.id = t.id;

commit;
"""


def test_oracle_conversion_removes_insert_hint_commit_and_rewrites_functions() -> None:
    result = convert_oracle_to_starrocks(ORACLE_SQL)

    assert result.target_table == "other.dm$partners_sales$p1"
    assert result.target_schema == "other"
    assert "insert" not in result.sql.lower()
    assert "append" not in result.sql.lower()
    assert "commit" not in result.sql.lower()
    assert "current_timestamp" in result.sql
    assert "coalesce" in result.sql
    assert "md5" in result.sql
    assert "s_md5" in result.sql


def test_resolved_conversion_reports_unresolved_tables(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    converted = convert_oracle_to_starrocks(ORACLE_SQL)

    resolved = resolve_tables(converted.sql, str(tmp_path), {})

    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in resolved.sql
    assert "unresolved table: unknown_schema.some_table" in resolved.warnings
