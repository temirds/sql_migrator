from __future__ import annotations

from file_utils import build_file_fields


def test_build_file_fields_schema_is_kept_out_of_model_name() -> None:
    fields = build_file_fields("../dbt_fs", "other.dm$partners_sales$p1")

    assert fields["target_schema"] == "other"
    assert fields["model_name"] == "DM_PARTNERS_SALES_P1"
    assert fields["base_object"] == "dm_partners_sales"
    assert fields["sql_file_name"] == "DM_PARTNERS_SALES_P1.sql"
    assert fields["yaml_file_name"] == "_DM_PARTNERS_SALES_MODELS.yml"


def test_build_file_fields_without_schema() -> None:
    fields = build_file_fields("../dbt_fs", "ds$bin_restrictions$b")

    assert fields["target_schema"] in {None, ""}
    assert fields["model_name"] == "DS_BIN_RESTRICTIONS_B"
    assert fields["base_object"] == "ds_bin_restrictions"
