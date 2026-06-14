from __future__ import annotations

from pathlib import Path

import yaml

try:
    from converter import get_base_object, normalize_model_name, parse_relation_name
except ModuleNotFoundError:
    from .converter import get_base_object, normalize_model_name, parse_relation_name


SQL_MIGRATOR_DIR = Path(__file__).resolve().parent


def resolve_path(path: str) -> Path:
    current = Path(path)
    if current.is_absolute():
        return current
    return (SQL_MIGRATOR_DIR / current).resolve()


def build_file_fields(project_dir: str, target_table: str) -> dict[str, str]:
    relation = parse_relation_name(target_table)
    model_name = normalize_model_name(target_table)
    base_object = get_base_object(model_name)
    return {
        "target_schema": relation["schema"] or "",
        "model_name": model_name,
        "base_object": base_object,
        "sql_file_name": f"{model_name}.sql",
        "yaml_file_name": f"_{base_object.upper()}_MODELS.yml",
        "save_dir": str(Path(project_dir) / "models" / base_object),
    }


def _model_config(schema_tag: str, base_model_name: str) -> dict:
    return {
        "tags": [schema_tag, base_model_name],
        "materialized": "truncate_insert",
        "description": "",
    }


def _first_schema_tag(models: list[dict], fallback: str) -> str:
    for model in models:
        tags = (model.get("config") or {}).get("tags")
        if isinstance(tags, list) and tags:
            return str(tags[0]).upper()
    return fallback


def _normalized_model(model: dict) -> dict:
    name = str(model["name"])
    base_model_name = get_base_object(name).upper()
    config = model.get("config") or {}
    tags = config.get("tags")
    if not isinstance(tags, list) or not tags:
        tags = ["OTHER", base_model_name]
    elif len(tags) == 1:
        tags = [str(tags[0]).upper(), base_model_name]
    else:
        tags = [str(tags[0]).upper(), base_model_name]

    return {
        "name": name,
        "config": {
            "tags": tags,
            "materialized": config.get("materialized") or "truncate_insert",
            "description": config.get("description") or "",
        },
    }


def render_models_yml(models: list[dict]) -> str:
    lines = ["version: 2", "", "models:"]
    for index, raw_model in enumerate(models):
        if index:
            lines.append("")

        model = _normalized_model(raw_model)
        tags = model["config"]["tags"]
        lines.extend(
            [
                f"  - name: {model['name']}",
                "    config:",
                f'      tags: ["{tags[0]}", "{tags[1]}"]',
                f"      materialized: {model['config']['materialized']}",
                "      description: ''",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_or_update_model_yml(
    yaml_path: Path,
    model_name: str,
    base_model_name: str,
    target_schema: str | None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    data: dict = {"version": 2, "models": []}

    if yaml_path.exists():
        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data.update(loaded)

    existing_models = data.get("models")
    if not isinstance(existing_models, list):
        existing_models = []

    schema_tag = _first_schema_tag(
        [model for model in existing_models if isinstance(model, dict)],
        (target_schema or "OTHER").upper(),
    )
    desired_config = _model_config(schema_tag, base_model_name)

    deduped: list[dict] = []
    name_positions: dict[str, int] = {}
    existing_position: int | None = None

    for model in existing_models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if not name:
            continue
        if name in name_positions:
            warnings.append(f"duplicate model {name} removed from YAML")
            deduped[name_positions[name]] = model
            if name == model_name:
                existing_position = name_positions[name]
            continue
        name_positions[name] = len(deduped)
        if name == model_name:
            existing_position = len(deduped)
        deduped.append(model)

    new_model = {
        "name": model_name,
        "config": desired_config,
    }
    if existing_position is None:
        deduped.append(new_model)
    else:
        current = dict(deduped[existing_position])
        current["config"] = desired_config
        deduped[existing_position] = current
        warnings.append(f"model {model_name} already exists in YAML, config updated")

    yaml_text = render_models_yml(deduped)
    return yaml_text, warnings


def save_model_files(
    sql: str,
    save_dir: str,
    sql_file_name: str,
    yaml_file_name: str,
    model_name: str,
    target_schema: str = "",
) -> tuple[list[str], list[str]]:
    logs: list[str] = []
    warnings: list[str] = []
    target_dir = resolve_path(save_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    sql_path = target_dir / sql_file_name
    sql_path.write_text(sql.rstrip() + "\n", encoding="utf-8")
    logs.append(f"Saved SQL: {sql_path}")

    yaml_path = target_dir / yaml_file_name
    base_model_name = get_base_object(model_name).upper()
    yaml_content, yaml_warnings = build_or_update_model_yml(
        yaml_path,
        model_name,
        base_model_name,
        target_schema,
    )
    warnings.extend(yaml_warnings)
    yaml_path.write_text(
        yaml_content,
        encoding="utf-8",
    )
    logs.extend(yaml_warnings)
    logs.append(f"Saved YAML: {yaml_path}")
    return logs, warnings
