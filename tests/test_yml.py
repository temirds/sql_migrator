from __future__ import annotations

from pathlib import Path

import yaml

from file_utils import build_or_update_model_yml


EXPECTED_TWO_MODELS = """version: 2

models:
  - name: DM_PARTNERS_SALES_P1
    config:
      tags: ["OTHER", "DM_PARTNERS_SALES"]
      materialized: truncate_insert
      description: ''

  - name: DM_PARTNERS_SALES_P2
    config:
      tags: ["OTHER", "DM_PARTNERS_SALES"]
      materialized: truncate_insert
      description: ''
"""


def test_create_new_yml_with_inline_tags(tmp_path: Path) -> None:
    content, warnings = build_or_update_model_yml(
        tmp_path / "_DM_PARTNERS_SALES_MODELS.yml",
        "DM_PARTNERS_SALES_P1",
        "DM_PARTNERS_SALES",
        "other",
    )

    assert warnings == []
    assert 'tags: ["OTHER", "DM_PARTNERS_SALES"]' in content
    assert "description: ''" in content
    assert yaml.safe_load(content)["models"][0]["name"] == "DM_PARTNERS_SALES_P1"


def test_add_p2_to_end_with_blank_line(tmp_path: Path) -> None:
    yaml_path = tmp_path / "_DM_PARTNERS_SALES_MODELS.yml"
    first, _ = build_or_update_model_yml(
        yaml_path,
        "DM_PARTNERS_SALES_P1",
        "DM_PARTNERS_SALES",
        "other",
    )
    yaml_path.write_text(first, encoding="utf-8")

    second, warnings = build_or_update_model_yml(
        yaml_path,
        "DM_PARTNERS_SALES_P2",
        "DM_PARTNERS_SALES",
        "other",
    )

    assert warnings == []
    assert second == EXPECTED_TWO_MODELS
    assert "\n\n  - name: DM_PARTNERS_SALES_P2" in second


def test_existing_model_updates_without_duplicate(tmp_path: Path) -> None:
    yaml_path = tmp_path / "_DM_PARTNERS_SALES_MODELS.yml"
    yaml_path.write_text(EXPECTED_TWO_MODELS, encoding="utf-8")

    content, warnings = build_or_update_model_yml(
        yaml_path,
        "DM_PARTNERS_SALES_P1",
        "DM_PARTNERS_SALES",
        "other",
    )

    assert content.count("- name: DM_PARTNERS_SALES_P1") == 1
    assert "model DM_PARTNERS_SALES_P1 already exists in YAML, config updated" in warnings


def test_existing_schema_tag_is_reused(tmp_path: Path) -> None:
    yaml_path = tmp_path / "_MODEL.yml"
    yaml_path.write_text(
        """version: 2

models:
  - name: DM_PARTNERS_SALES_P1
    config:
      tags: ["CUSTOM", "DM_PARTNERS_SALES"]
      materialized: truncate_insert
      description: ''
""",
        encoding="utf-8",
    )

    content, _ = build_or_update_model_yml(
        yaml_path,
        "DM_PARTNERS_SALES_P2",
        "DM_PARTNERS_SALES",
        "other",
    )

    assert 'tags: ["CUSTOM", "DM_PARTNERS_SALES"]' in content
