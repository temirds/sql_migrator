from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess

import yaml

try:
    from converter import get_base_object, normalize_model_name, parse_relation_name
except ModuleNotFoundError:
    from .converter import get_base_object, normalize_model_name, parse_relation_name


SQL_MIGRATOR_DIR = Path(__file__).resolve().parent


@dataclass
class CommandResult:
    command_text: str
    cwd: Path
    return_code: int
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    def to_log(self) -> str:
        return "\n".join(
            [
                f"cwd: {self.cwd}",
                f"command args: {self.command_text_args}",
                f"command text: {self.command_text}",
                f"return code: {self.return_code}",
                "stdout:",
                self.stdout.strip(),
                "stderr:",
                self.stderr.strip(),
                "error:",
                self.error.strip(),
            ]
        )

    @property
    def command_text_args(self) -> str:
        return repr(shlex.split(self.command_text, posix=False))


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


def command_text(command: list[str]) -> str:
    return " ".join(command)


def format_command_log(result: CommandResult, command: list[str]) -> str:
    return "\n".join(
        [
            f"cwd: {result.cwd}",
            f"command args: {command!r}",
            f"command text: {result.command_text}",
            f"return code: {result.return_code}",
            "stdout:",
            result.stdout.strip(),
            "stderr:",
            result.stderr.strip(),
            "error:",
            result.error.strip(),
        ]
    )


def run_command(command: list[str], cwd: Path) -> CommandResult:
    command_as_text = command_text(command)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=False,
        )
        return CommandResult(
            command_text=command_as_text,
            cwd=cwd,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError:
        return CommandResult(
            command_text=command_as_text,
            cwd=cwd,
            return_code=1,
            error=(
                "dbt executable not found. Check that dbt is installed and available "
                f"in PATH.\nPATH: {os.environ.get('PATH', '')}"
            ),
        )
    except Exception as exc:
        return CommandResult(
            command_text=command_as_text,
            cwd=cwd,
            return_code=1,
            error=f"dbt command error: {exc}",
        )


def run_dbt(project_dir: str, args: list[str]) -> tuple[int, str]:
    command = ["dbt", *args]
    result = run_command(command, resolve_path(project_dir))
    return result.return_code, format_command_log(result, command)
