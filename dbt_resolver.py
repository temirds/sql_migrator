from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

import yaml

try:
    from converter import normalize_name
    from file_utils import resolve_path
except ModuleNotFoundError:
    from .converter import normalize_name
    from .file_utils import resolve_path


TABLE_RE = re.compile(
    r"\b(from|join)\s+(`?[\w$#]+`?(?:\.`?[\w$#]+`?)?)",
    re.IGNORECASE,
)


@dataclass
class ResolveResult:
    raw_table: str
    replacement: str
    found: bool
    kind: str
    model_name: str = ""
    xref_schema: str = ""
    warning: str = ""


@dataclass
class ResolveSqlResult:
    sql: str
    warnings: list[str]
    logs: list[str]


def load_config(config_path: str | Path | None = None) -> dict:
    path = Path(config_path) if config_path else Path(__file__).with_name("config.yml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def normalize_relation_part(value: str) -> str:
    return normalize_name(value.replace("`", "").replace('"', ""))


def parse_relation(raw_table: str) -> tuple[str | None, str]:
    clean = raw_table.strip().replace("`", "").replace('"', "")
    parts = [part for part in clean.split(".") if part]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[-1] if parts else clean


def _schema_for_model(model_name: str) -> str:
    return "DWH_STAGE" if model_name.upper().startswith("STG__") else "PROD"


def _xref(model_name: str, schema: str | None = None) -> str:
    xref_schema = schema or _schema_for_model(model_name)
    return "{{ xref('" + model_name + "', '" + xref_schema + "') }}"


class DbtResolver:
    def __init__(self, project_dir: Path, config: dict):
        self.project_dir = project_dir
        self.config = config
        self.logs: list[str] = []
        self.manifest_path = resolve_path(str(project_dir / "target" / "manifest.json"))
        self.models = self._load_models()
        self.sources = self._load_sources()
        self.manifest_missing = not self.manifest_path.exists()

    def resolve_table(self, raw_table: str) -> ResolveResult:
        if self.manifest_missing:
            return ResolveResult(
                raw_table=raw_table,
                replacement=raw_table,
                found=False,
                kind="unresolved",
                warning="manifest.json not found, run dbt parse",
            )

        manual = self._manual_override(raw_table)
        if manual:
            schema = _schema_for_model(manual)
            return ResolveResult(
                raw_table=raw_table,
                replacement=_xref(manual, schema),
                found=True,
                kind="model",
                model_name=manual,
                xref_schema=schema,
            )

        schema, table = parse_relation(raw_table)
        normalized_schema = normalize_relation_part(schema or "")
        normalized_table = normalize_relation_part(table)

        if normalized_schema == "DWH_STAGE2":
            preferred_model = f"STG__{normalized_table}"
            found = self._find_model(preferred_model)
            if found:
                return ResolveResult(
                    raw_table=raw_table,
                    replacement=_xref(found, "DWH_STAGE"),
                    found=True,
                    kind="model",
                    model_name=found,
                    xref_schema="DWH_STAGE",
                )

        candidates = [
            raw_table,
            f"{schema}.{table}" if schema else table,
            table,
            normalized_table,
            normalize_relation_part(raw_table),
        ]
        found = self._find_unique_model(candidates)
        if found:
            xref_schema = _schema_for_model(found)
            return ResolveResult(
                raw_table=raw_table,
                replacement=_xref(found, xref_schema),
                found=True,
                kind="model",
                model_name=found,
                xref_schema=xref_schema,
            )

        if self._find_source(candidates):
            return ResolveResult(
                raw_table=raw_table,
                replacement=raw_table,
                found=True,
                kind="source",
                warning=f"source found but model/xref not found: {raw_table}",
            )

        return ResolveResult(
            raw_table=raw_table,
            replacement=raw_table,
            found=False,
            kind="unresolved",
            warning=f"unresolved table: {raw_table}",
        )

    def _load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _load_models(self) -> dict[str, list[str]]:
        manifest = self._load_manifest()
        models: dict[str, list[str]] = {}
        for node in manifest.get("nodes", {}).values():
            if node.get("resource_type") != "model":
                continue
            model_name = node.get("name") or ""
            alias = node.get("alias") or model_name
            identifier = node.get("identifier") or alias
            schema = node.get("schema") or ""
            keys = {model_name, alias, identifier}
            if schema:
                keys.add(f"{schema}.{alias}")
                keys.add(f"{schema}.{identifier}")
            for key in keys:
                self._add_index(models, key, model_name)
        return models

    def _load_sources(self) -> dict[str, list[str]]:
        manifest = self._load_manifest()
        sources: dict[str, list[str]] = {}
        for source in manifest.get("sources", {}).values():
            source_name = source.get("source_name") or ""
            name = source.get("name") or ""
            identifier = source.get("identifier") or name
            schema = source.get("schema") or source_name
            keys = {name, identifier}
            if schema:
                keys.add(f"{schema}.{name}")
                keys.add(f"{schema}.{identifier}")
            for key in keys:
                self._add_index(sources, key, name)
        return sources

    def _add_index(self, index: dict[str, list[str]], key: str, value: str) -> None:
        if not key or not value:
            return
        index.setdefault(key.upper(), []).append(value)
        index.setdefault(normalize_relation_part(key), []).append(value)

    def _manual_override(self, table_name: str) -> str | None:
        overrides = self.config.get("manual_overrides") or {}
        variants = {table_name.upper(), normalize_relation_part(table_name)}
        for key, value in overrides.items():
            if key.upper() in variants or normalize_relation_part(key) in variants:
                if value.get("type") == "model":
                    return value.get("model_name")
        return None

    def _find_model(self, key: str) -> str | None:
        found = self.models.get(key.upper()) or self.models.get(normalize_relation_part(key)) or []
        unique = sorted(set(found))
        return unique[0] if len(unique) == 1 else None

    def _find_unique_model(self, keys: list[str]) -> str | None:
        found: list[str] = []
        for key in keys:
            found.extend(self.models.get(key.upper()) or [])
            found.extend(self.models.get(normalize_relation_part(key)) or [])
        unique = sorted(set(found))
        return unique[0] if len(unique) == 1 else None

    def _find_source(self, keys: list[str]) -> str | None:
        found: list[str] = []
        for key in keys:
            found.extend(self.sources.get(key.upper()) or [])
            found.extend(self.sources.get(normalize_relation_part(key)) or [])
        unique = sorted(set(found))
        return unique[0] if len(unique) == 1 else None


def resolve_tables(sql: str, project_dir: str, config: dict | None = None) -> ResolveSqlResult:
    config = config or load_config()
    resolver = DbtResolver(resolve_path(project_dir), config)
    warnings: list[str] = []
    logs: list[str] = []
    manifest_warning_added = False

    def replace(match: re.Match) -> str:
        nonlocal manifest_warning_added
        keyword = match.group(1)
        raw_name = match.group(2).replace("`", "")
        result = resolver.resolve_table(raw_name)
        if result.warning:
            if result.warning == "manifest.json not found, run dbt parse":
                if not manifest_warning_added:
                    warnings.append(result.warning)
                    manifest_warning_added = True
            else:
                warnings.append(result.warning)
        if result.found and result.kind == "model":
            logs.append(
                f"resolved table {raw_name} -> xref('{result.model_name}', '{result.xref_schema}')"
            )
        return f"{keyword} {result.replacement}"

    return ResolveSqlResult(sql=TABLE_RE.sub(replace, sql), warnings=warnings, logs=logs)
