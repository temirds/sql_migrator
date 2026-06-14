from __future__ import annotations

import json
from pathlib import Path
import sys


SQL_MIGRATOR_DIR = Path(__file__).resolve().parents[1]
if str(SQL_MIGRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(SQL_MIGRATOR_DIR))


def write_manifest(project_dir: Path) -> Path:
    manifest = {
        "nodes": {
            "model.dbt_fs.STG__S01_Z_CLIENT": {
                "resource_type": "model",
                "name": "STG__S01_Z_CLIENT",
                "alias": "STG__S01_Z_CLIENT",
                "schema": "DWH_STAGE",
                "unique_id": "model.dbt_fs.STG__S01_Z_CLIENT",
            },
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
        },
        "sources": {},
    }
    target_dir = project_dir / "target"
    target_dir.mkdir(parents=True)
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path
