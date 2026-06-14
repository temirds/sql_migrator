from __future__ import annotations

import json
from pathlib import Path
import sys


SQL_MIGRATOR_DIR = Path(__file__).resolve().parents[1]
if str(SQL_MIGRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(SQL_MIGRATOR_DIR))


def write_manifest(
    project_dir: Path,
    *,
    include_s01_model: bool = True,
    include_tradepoint_model: bool = False,
    include_tradepoint_partial_model: bool = False,
    include_sources: bool = False,
) -> Path:
    nodes = {}
    if include_s01_model:
        nodes["model.dbt_fs.STG__S01_Z_CLIENT"] = {
            "resource_type": "model",
            "name": "STG__S01_Z_CLIENT",
            "alias": "STG__S01_Z_CLIENT",
            "schema": "DWH_STAGE",
            "unique_id": "model.dbt_fs.STG__S01_Z_CLIENT",
        }
    nodes.update(
        {
        "model.dbt_fs.DS_BIN_RESTRICTIONS_P": {
            "resource_type": "model",
            "name": "DS_BIN_RESTRICTIONS_P",
            "alias": "DS_BIN_RESTRICTIONS_P",
            "schema": "PROD",
            "unique_id": "model.dbt_fs.DS_BIN_RESTRICTIONS_P",
        },
        "model.dbt_fs.DM_PARTNERS_SALES_P1": {
            "resource_type": "model",
            "name": "DM_PARTNERS_SALES_P1",
            "alias": "DM_PARTNERS_SALES_P1",
            "schema": "PROD",
            "unique_id": "model.dbt_fs.DM_PARTNERS_SALES_P1",
        },
        }
    )
    if include_tradepoint_model:
        nodes["model.dbt_fs.STG__S0090_TRADEPOINT_ONL_HISTORY"] = {
            "resource_type": "model",
            "name": "STG__S0090_TRADEPOINT_ONL_HISTORY",
            "alias": "STG__S0090_TRADEPOINT_ONL_HISTORY",
            "schema": "DWH_STAGE",
            "unique_id": "model.dbt_fs.STG__S0090_TRADEPOINT_ONL_HISTORY",
        }
    if include_tradepoint_partial_model:
        nodes["model.dbt_fs.STG__S0090_TRADEPOINT_ONL"] = {
            "resource_type": "model",
            "name": "STG__S0090_TRADEPOINT_ONL",
            "alias": "STG__S0090_TRADEPOINT_ONL",
            "schema": "DWH_STAGE",
            "unique_id": "model.dbt_fs.STG__S0090_TRADEPOINT_ONL",
        }

    sources = {}
    if include_sources:
        sources = {
            "source.dbt_fs.s0090.tradepoint_onl_history": {
                "resource_type": "source",
                "source_name": "S0090",
                "name": "TRADEPOINT_ONL_HISTORY",
                "identifier": "TRADEPOINT_ONL_HISTORY",
                "schema": "S0090",
            },
            "source.dbt_fs.s01.z_client": {
                "resource_type": "source",
                "source_name": "S01",
                "name": "Z_CLIENT",
                "identifier": "Z_CLIENT",
                "schema": "S01",
            },
        }

    manifest = {
        "nodes": nodes,
        "sources": sources,
    }
    target_dir = project_dir / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path
