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
    r"\b(from|join)\s+(`?[\w$#]+`?(?:\.`?[\w$#]+`?)*)",
    re.IGNORECASE,
)
RAW_TABLE_REF_RE = re.compile(
    r"\b(from|join|update|merge\s+into)\s+([a-zA-Z0-9_$#]+(?:\.[a-zA-Z0-9_$#]+)?)",
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
    logs: list[str] | None = None


@dataclass
class ResolveSqlResult:
    sql: str
    warnings: list[str]
    logs: list[str]


@dataclass
class SourceRef:
    source_name: str
    name: str
    identifier: str
    schema: str


@dataclass
class DwhStage2Ref:
    source_schema: str
    source_table: str
    preferred_model: str
    starrocks_physical: str


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
    if len(parts) >= 3 and normalize_relation_part(parts[0]) == "DWH_STAGE2":
        return parts[0], "_".join(parts[1:])
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[-1] if parts else clean


def _schema_for_model(model_name: str) -> str:
    return "DWH_STAGE" if model_name.upper().startswith("STG__") else "PROD"


def _xref(model_name: str, schema: str | None = None) -> str:
    xref_schema = schema or _schema_for_model(model_name)
    return "{{ xref('" + model_name + "', '" + xref_schema + "') }}"


def _source(source_name: str, name: str) -> str:
    return "{{ source('" + source_name + "', '" + name + "') }}"


def parse_dwh_stage2_table(table: str) -> dict[str, str]:
    parsed = parse_dwh_stage2_reference("DWH_STAGE2", table)
    return {
        "source_schema": parsed.source_schema,
        "source_table": parsed.source_table,
        "preferred_model": parsed.preferred_model,
    }


def parse_dwh_stage2_reference(raw_schema: str, raw_table: str) -> DwhStage2Ref:
    clean = raw_table.strip().replace("`", "").replace('"', "")
    separator = "$" if "$" in clean else "#" if "#" in clean else ""

    if separator:
        source_schema, source_table = clean.split(separator, 1)
    else:
        source_schema = ""
        source_table = clean

    normalized_schema = normalize_relation_part(source_schema)
    normalized_table = normalize_relation_part(source_table)
    preferred_parts = [part for part in [normalized_schema, normalized_table] if part]
    preferred_model = "STG__" + "_".join(preferred_parts)
    if normalized_schema:
        starrocks_physical = f"{normalized_schema}.{normalized_table}"
    else:
        starrocks_physical = normalized_table

    return DwhStage2Ref(
        source_schema=normalized_schema,
        source_table=normalized_table,
        preferred_model=preferred_model,
        starrocks_physical=starrocks_physical,
    )


class DbtResolver:
    def __init__(self, project_dir: Path, config: dict):
        self.project_dir = project_dir
        self.config = config
        self.logs: list[str] = []
        self.manifest_path = resolve_path(str(project_dir / "target" / "manifest.json"))
        self.models = self._load_models()
        self.sources = self._load_sources()
        self.source_refs = self._load_source_refs()
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
            dwh_table = parse_dwh_stage2_reference(schema or "", table)
            logs = [
                f"resolver input raw: {raw_table}",
                "parsed DWH_STAGE2:",
                f"  source_schema: {dwh_table.source_schema}",
                f"  source_table: {dwh_table.source_table}",
                f"  preferred_model: {dwh_table.preferred_model}",
                "model lookup:",
                f"  candidate: {dwh_table.preferred_model}",
            ]
            found = self._find_model(dwh_table.preferred_model)
            logs.append(f"  found: {str(bool(found)).lower()}")
            if found:
                logs.extend(
                    [
                        "resolved:",
                        f"  {raw_table} -> xref('{found}', 'DWH_STAGE')",
                    ]
                )
                return ResolveResult(
                    raw_table=raw_table,
                    replacement=_xref(found, "DWH_STAGE"),
                    found=True,
                    kind="model",
                    model_name=found,
                    xref_schema="DWH_STAGE",
                    logs=logs,
                )

            logs.extend(
                [
                    "source lookup:",
                    f"  source_schema: {dwh_table.source_schema}",
                    f"  source_table: {dwh_table.source_table}",
                ]
            )
            source = self._find_dwh_stage2_source(
                dwh_table.source_schema,
                dwh_table.source_table,
            )
            logs.append(f"  found: {str(bool(source)).lower()}")
            if source:
                logs.extend(
                    [
                        "resolved:",
                        f"  {raw_table} -> source('{source.source_name}', '{source.name}')",
                    ]
                )
                return ResolveResult(
                    raw_table=raw_table,
                    replacement=_source(source.source_name, source.name),
                    found=True,
                    kind="source",
                    logs=logs,
                )

            logs.extend(
                [
                    "resolved:",
                    f"  {raw_table} -> {dwh_table.starrocks_physical}",
                ]
            )
            return ResolveResult(
                raw_table=raw_table,
                replacement=dwh_table.starrocks_physical,
                found=False,
                kind="unresolved",
                warning=(
                    f"unresolved table: {raw_table}, "
                    f"fallback physical: {dwh_table.starrocks_physical}"
                ),
                logs=logs,
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
        for source in self._load_source_refs_from_manifest(manifest):
            name = source.name
            identifier = source.identifier
            schema = source.schema
            keys = {name, identifier}
            if schema:
                keys.add(f"{schema}.{name}")
                keys.add(f"{schema}.{identifier}")
            for key in keys:
                self._add_index(sources, key, name)
        return sources

    def _load_source_refs(self) -> list[SourceRef]:
        return self._load_source_refs_from_manifest(self._load_manifest())

    def _load_source_refs_from_manifest(self, manifest: dict) -> list[SourceRef]:
        refs: list[SourceRef] = []
        for source in manifest.get("sources", {}).values():
            source_name = source.get("source_name") or ""
            name = source.get("name") or ""
            identifier = source.get("identifier") or name
            schema = source.get("schema") or source_name
            if source_name and name:
                refs.append(
                    SourceRef(
                        source_name=source_name,
                        name=name,
                        identifier=identifier,
                        schema=schema,
                    )
                )
        return refs

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

    def _find_dwh_stage2_source(self, source_schema: str, source_table: str) -> SourceRef | None:
        if not source_schema or not source_table:
            return None

        matches: list[SourceRef] = []
        for source in self.source_refs:
            schema_matches = source.source_name.upper() == source_schema or normalize_relation_part(
                source.schema
            ) == source_schema
            table_matches = (
                source.name.upper() == source_table
                or source.identifier.upper() == source_table
                or normalize_relation_part(source.name) == source_table
                or normalize_relation_part(source.identifier) == source_table
            )
            if schema_matches and table_matches:
                matches.append(source)

        unique = {(source.source_name, source.name): source for source in matches}
        return next(iter(unique.values())) if len(unique) == 1 else None


def extract_raw_table_refs(raw_sql: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for match in RAW_TABLE_REF_RE.finditer(raw_sql):
        ref = match.group(2).strip().strip("`").strip('"')
        key = ref.upper()
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def _replacement_keys_for_raw_ref(raw_ref: str) -> set[str]:
    keys = {normalize_relation_part(raw_ref)}
    schema, table = parse_relation(raw_ref)
    normalized_schema = normalize_relation_part(schema or "")
    normalized_table = normalize_relation_part(table)

    if normalized_schema == "DWH_STAGE2":
        dwh_table = parse_dwh_stage2_reference(schema or "", table)
        keys.add(normalize_relation_part(f"{schema}.{dwh_table.source_schema}_{dwh_table.source_table}"))
        keys.add(normalize_relation_part(dwh_table.starrocks_physical))
        keys.add(normalize_relation_part(f"{schema}.{normalized_table}"))
    return keys


def resolve_tables(
    sql: str,
    project_dir: str,
    config: dict | None = None,
    raw_sql: str | None = None,
) -> ResolveSqlResult:
    config = config or load_config()
    resolver = DbtResolver(resolve_path(project_dir), config)
    warnings: list[str] = []
    logs: list[str] = []
    manifest_warning_added = False
    raw_replacements: dict[str, ResolveResult] = {}

    if raw_sql:
        for raw_ref in extract_raw_table_refs(raw_sql):
            result = resolver.resolve_table(raw_ref)
            if result.logs:
                logs.extend(result.logs)
            if result.warning:
                warnings.append(result.warning)
            for key in _replacement_keys_for_raw_ref(raw_ref):
                raw_replacements[key] = result

    def replace(match: re.Match) -> str:
        nonlocal manifest_warning_added
        keyword = match.group(1)
        raw_name = match.group(2).replace("`", "")
        replacement_key = normalize_relation_part(raw_name)
        result = raw_replacements.get(replacement_key)
        if result is None:
            result = resolver.resolve_table(raw_name)
            if result.logs:
                logs.extend(result.logs)
        if result.warning:
            if result.warning == "manifest.json not found, run dbt parse":
                if not manifest_warning_added:
                    warnings.append(result.warning)
                    manifest_warning_added = True
            elif result.warning not in warnings:
                warnings.append(result.warning)
        if result.found and result.kind == "model":
            summary = f"{result.raw_table} -> xref('{result.model_name}', '{result.xref_schema}')"
            if summary not in logs:
                logs.append(summary)
        elif result.found and result.kind == "source":
            summary = f"{result.raw_table} -> {result.replacement.strip('{} ')}"
            if summary not in logs:
                logs.append(summary)
        return f"{keyword} {result.replacement}"

    return ResolveSqlResult(sql=TABLE_RE.sub(replace, sql), warnings=warnings, logs=logs)
