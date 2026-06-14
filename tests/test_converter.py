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

    resolved = resolve_tables(converted.sql, str(tmp_path), {}, raw_sql=ORACLE_SQL)

    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in resolved.sql
    assert "unresolved table: UNKNOWN_SCHEMA.SOME_TABLE" in resolved.warnings


def test_converter_integration_uses_raw_dwh_stage2_references(tmp_path: Path) -> None:
    raw_sql = """
insert into DS$BIN_RESTRICTIONS$P
select *
from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY h
join DWH_STAGE2.S01#Z_CLIENT c
  on c.id = h.client_id;
"""
    write_manifest(tmp_path, include_tradepoint_model=True, include_sources=True)
    converted = convert_oracle_to_starrocks(raw_sql)

    resolved = resolve_tables(converted.sql, str(tmp_path), {}, raw_sql=raw_sql)

    assert "{{ xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE') }}" in resolved.sql
    assert "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in resolved.sql
    lowered = resolved.sql.lower()
    assert "dwh_stage2.s0090_tradepoint_onl_history" not in lowered
    assert "dwh_stage2.s0090_tradepoint_onl" not in lowered
    assert "s01.z_client" not in lowered
    assert "STG__S0090_TRADEPOINT_ONL'" not in resolved.sql


def test_removes_hint_commit_insert_and_trailing_semicolon() -> None:
    sql = """
insert /*+ append enable_parallel_dml parallel(20) */
into DS$BIN_RESTRICTIONS$P
select *
from DWH_STAGE2.S01#Z_CLIENT;

commit;
"""

    result = convert_oracle_to_starrocks(sql)

    assert "/*+" not in result.sql
    assert "append" not in result.sql
    assert "parallel" not in result.sql
    assert "commit" not in result.sql.lower()
    assert not result.sql.rstrip().endswith(";")
    assert "select" in result.sql.lower()
    assert "insert into" not in result.sql.lower()


def test_removes_normal_comments_commit_and_trailing_semicolon() -> None:
    sql = """
-- top comment
insert into DS$BIN_RESTRICTIONS$P
select /* middle comment */ *
from DWH_STAGE2.S01#Z_CLIENT -- source comment
where 1 = 1;

commit;
"""

    result = convert_oracle_to_starrocks(sql)

    assert "--" not in result.sql
    assert "/*" not in result.sql
    assert "*/" not in result.sql
    assert "commit" not in result.sql.lower()
    assert not result.sql.rstrip().endswith(";")


def test_final_cleanup_after_resolver(tmp_path: Path) -> None:
    raw_sql = """
insert into DS$BIN_RESTRICTIONS$P
select *
from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY h;

commit;
"""
    write_manifest(tmp_path, include_tradepoint_model=True, include_sources=True)
    converted = convert_oracle_to_starrocks(raw_sql)
    resolved = resolve_tables(converted.sql + ";\n-- dirty\ncommit;", str(tmp_path), {}, raw_sql=raw_sql)

    assert "{{ xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE') }}" in resolved.sql
    assert "commit" not in resolved.sql.lower()
    assert not resolved.sql.rstrip().endswith(";")
    assert "/*" not in resolved.sql
    assert "--" not in resolved.sql
    assert "dwh_stage2." not in resolved.sql.lower()


def test_target_extraction_still_works_with_hint() -> None:
    sql = """
insert /*+ append */ into DS$BIN_RESTRICTIONS$P
select 1 from dual;
commit;
"""

    result = convert_oracle_to_starrocks(sql)

    assert result.target_table == "DS$BIN_RESTRICTIONS$P"
    assert result.model_name == "DS_BIN_RESTRICTIONS_P"
    assert "insert" not in result.sql.lower()
    assert "append" not in result.sql.lower()
    assert "commit" not in result.sql.lower()
    assert not result.sql.rstrip().endswith(";")
