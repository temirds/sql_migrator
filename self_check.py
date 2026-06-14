from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from converter import clean_converted_sql, clean_oracle_sql, convert_oracle_to_starrocks
from dbt_resolver import resolve_tables
from file_utils import build_or_update_model_yml
import state


def write_manifest(project_dir: Path, *, partial_only: bool = False) -> None:
    nodes = {
        "model.dbt_fs.STG__S01_Z_CLIENT": {
            "resource_type": "model",
            "name": "STG__S01_Z_CLIENT",
            "alias": "STG__S01_Z_CLIENT",
            "schema": "DWH_STAGE",
        }
    }
    if partial_only:
        nodes["model.dbt_fs.STG__S0090_TRADEPOINT_ONL"] = {
            "resource_type": "model",
            "name": "STG__S0090_TRADEPOINT_ONL",
            "alias": "STG__S0090_TRADEPOINT_ONL",
            "schema": "DWH_STAGE",
        }
    else:
        nodes["model.dbt_fs.STG__S0090_TRADEPOINT_ONL_HISTORY"] = {
            "resource_type": "model",
            "name": "STG__S0090_TRADEPOINT_ONL_HISTORY",
            "alias": "STG__S0090_TRADEPOINT_ONL_HISTORY",
            "schema": "DWH_STAGE",
        }

    manifest = {
        "nodes": nodes,
        "sources": {
            "source.dbt_fs.S0090.TRADEPOINT_ONL_HISTORY": {
                "resource_type": "source",
                "source_name": "S0090",
                "name": "TRADEPOINT_ONL_HISTORY",
                "identifier": "TRADEPOINT_ONL_HISTORY",
                "schema": "S0090",
            },
            "source.dbt_fs.S01.Z_CLIENT": {
                "resource_type": "source",
                "source_name": "S01",
                "name": "Z_CLIENT",
                "identifier": "Z_CLIENT",
                "schema": "S01",
            },
        },
    }
    target_dir = project_dir / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def check(name: str, condition: bool, details: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"{status}: {name}")
    if details and not condition:
        print(details)
    return condition


def main() -> int:
    failures = 0
    cleanup_sql = """
-- top comment
insert /*+ append enable_parallel_dml parallel(20) */ into DS$BIN_RESTRICTIONS$P
select /* middle comment */ *
from DWH_STAGE2.S01#Z_CLIENT -- source comment
where 1 = 1;

commit;
"""
    cleanup_result = convert_oracle_to_starrocks(cleanup_sql)
    failures += not check("clean_oracle_sql", "commit" not in clean_oracle_sql(cleanup_sql).lower())
    failures += not check("clean_converted_sql", not clean_converted_sql("select 1;\ncommit;").endswith(";"))
    failures += not check("target extraction", cleanup_result.target_table == "DS$BIN_RESTRICTIONS$P")
    failures += not check("comments removed", "--" not in cleanup_result.sql and "/*" not in cleanup_result.sql and "*/" not in cleanup_result.sql, cleanup_result.sql)
    failures += not check("hints removed", "/*+" not in cleanup_result.sql and "append" not in cleanup_result.sql and "parallel" not in cleanup_result.sql, cleanup_result.sql)
    failures += not check("commit removed", "commit" not in cleanup_result.sql.lower(), cleanup_result.sql)
    failures += not check("trailing semicolon removed", not cleanup_result.sql.rstrip().endswith(";"), cleanup_result.sql)
    failures += not check("insert into removed", "insert into" not in cleanup_result.sql.lower(), cleanup_result.sql)

    keep_sql = """
insert into DS$BIN_RESTRICTIONS$P
select replace(max(brand) keep(dense_rank last order by tt.updated), ' ') as brand
from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY tt;
commit;
"""
    keep_result = convert_oracle_to_starrocks(keep_sql)
    keep_warnings = "\n".join(keep_result.warnings)
    failures += not check(
        "detects Oracle KEEP aggregate",
        "Oracle KEEP" in keep_warnings,
        keep_warnings or keep_result.sql,
    )
    failures += not check(
        "does not silently accept Oracle KEEP",
        bool(keep_result.warnings),
        keep_result.sql,
    )

    normal_result = convert_oracle_to_starrocks(
        """
insert into DS$BIN_RESTRICTIONS$P
select coalesce(name, 'N/A') as name
from DWH_STAGE2.S01#Z_CLIENT;
"""
    )
    normal_warnings = "\n".join(normal_result.warnings)
    failures += not check(
        "normal SQL has no unsupported warnings",
        "Oracle-only construct" not in normal_warnings
        and "Oracle KEEP" not in normal_warnings
        and "not supported" not in normal_warnings,
        normal_warnings,
    )

    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "_DM_PARTNERS_SALES_MODELS.yml"
        yaml_text, _ = build_or_update_model_yml(
            yaml_path,
            "DM_PARTNERS_SALES_P1",
            "DM_PARTNERS_SALES",
            "other",
        )
        failures += not check(
            "yaml rendering",
            'tags: ["OTHER", "DM_PARTNERS_SALES"]' in yaml_text
            and "description: ''" in yaml_text,
            yaml_text,
        )

    with tempfile.TemporaryDirectory() as tmp:
        original_path = state.PERSISTENT_STATE_PATH
        state.PERSISTENT_STATE_PATH = Path(tmp) / ".sql_migrator_state.json"
        try:
            state.save_persistent_state({"last_base_path": "../dbt_fs/models/other"})
            loaded_state, warning = state.load_persistent_state()
            failures += not check(
                "base_path persistence",
                warning is None and loaded_state.get("last_base_path") == "../dbt_fs/models/other",
            )
        finally:
            state.PERSISTENT_STATE_PATH = original_path

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        write_manifest(project_dir)

        trade = resolve_tables(
            "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
            str(project_dir),
            {},
        )
        failures += not check(
            "DWH_STAGE2 dollar resolves exact STG",
            "{{ xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE') }}" in trade.sql,
            trade.sql,
        )
        failures += not check(
            "DWH_STAGE2 hash resolves exact STG",
            "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}"
            in resolve_tables("select * from DWH_STAGE2.S01#Z_CLIENT", str(project_dir), {}).sql,
        )

        raw_sql = """
insert into DS$BIN_RESTRICTIONS$P
select *
from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY h
join DWH_STAGE2.S01#Z_CLIENT c
  on c.id = h.client_id;
"""
        converted = convert_oracle_to_starrocks(raw_sql)
        integrated = resolve_tables(converted.sql, str(project_dir), {}, raw_sql=raw_sql)
        lowered = integrated.sql.lower()
        failures += not check(
            "converter integration keeps exact tradepoint replacement",
            "{{ xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE') }}" in integrated.sql,
            integrated.sql,
        )
        failures += not check(
            "converter integration keeps exact z_client replacement",
            "{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}" in integrated.sql,
            integrated.sql,
        )
        failures += not check(
            "no unresolved dwh_stage2 result",
            "dwh_stage2." not in lowered,
            integrated.sql,
        )
        failures += not check(
            "no s01.z_client result for original DWH_STAGE2 hash",
            "s01.z_client" not in lowered,
            integrated.sql,
        )

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        write_manifest(project_dir, partial_only=True)
        partial = resolve_tables(
            "select * from DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY",
            str(project_dir),
            {},
        )
        failures += not check(
            "no partial match to STG__S0090_TRADEPOINT_ONL",
            "STG__S0090_TRADEPOINT_ONL'" not in partial.sql
            and "{{ source('S0090', 'TRADEPOINT_ONL_HISTORY') }}" in partial.sql,
            partial.sql,
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
