from __future__ import annotations

from dataclasses import dataclass, field
import re

import sqlglot
from sqlglot import exp


ORACLE_HINT_RE = re.compile(r"/\*\+.*?\*/", re.DOTALL)
COMMIT_RE = re.compile(r"^\s*commit\s*;?\s*$", re.IGNORECASE)
INSERT_RE = re.compile(
    r"^\s*insert\s*(?:/\*\+.*?\*/\s*)?(?:into\s+)?(?P<table>[^\s(]+)"
    r"\s*(?:\([^)]*\)\s*)?(?P<select>select\b.*)$",
    re.IGNORECASE | re.DOTALL,
)
JINJA_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
TECH_SUFFIX_RE = re.compile(r"(_(?:P\d*(?:_\d+)?|B\d*|G\d*|S|T|TMP))$", re.IGNORECASE)

ORACLE_UNSUPPORTED_PATTERNS = [
    {
        "name": "oracle_keep_dense_rank",
        "regex": r"\bkeep\s*\(\s*dense_rank\s+(first|last)\s+order\s+by\b",
        "message": (
            "Oracle KEEP (DENSE_RANK FIRST/LAST ORDER BY ...) is not supported "
            "by StarRocks and requires manual rewrite."
        ),
        "severity": "error",
        "suggestion": "Rewrite with explicit windowing or a verified StarRocks aggregate strategy.",
    },
]

ORACLE_ONLY_DETECT_PATTERNS = [
    ("KEEP", r"\bkeep\s*\("),
    ("DENSE_RANK", r"\bdense_rank\b"),
    ("CONNECT BY", r"\bconnect\s+by\b"),
    ("START WITH", r"\bstart\s+with\b"),
    ("ROWNUM", r"\brownum\b"),
    ("NVL", r"\bnvl\s*\("),
    ("SYSDATE", r"\bsysdate\b"),
    ("SYSTIMESTAMP", r"\bsystimestamp\b"),
    ("DECODE", r"\bdecode\s*\("),
    ("MINUS", r"\bminus\b"),
    ("DUAL", r"\bdual\b"),
    ("TO_DATE", r"\bto_date\s*\("),
    ("TO_CHAR", r"\bto_char\s*\("),
    ("TO_NUMBER", r"\bto_number\s*\("),
    ("ADD_MONTHS", r"\badd_months\s*\("),
    ("TRUNC", r"\btrunc\s*\("),
]


@dataclass
class ConversionResult:
    sql: str = ""
    target_table: str = ""
    target_schema: str = ""
    model_name: str = ""
    base_object: str = ""
    warnings: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


def normalize_name(name: str) -> str:
    normalized = re.sub(r"[$#.\s]+", "_", name.strip())
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized.upper()


def parse_relation_name(raw_name: str) -> dict[str, str | None]:
    raw = raw_name.strip().strip('"').strip("`")
    parts = [part.strip().strip('"').strip("`") for part in raw.split(".")]
    if len(parts) >= 2:
        return {
            "schema": parts[-2],
            "table": parts[-1],
            "raw": raw,
        }
    return {
        "schema": None,
        "table": raw,
        "raw": raw,
    }


def normalize_model_name(name: str) -> str:
    relation = parse_relation_name(name)
    return normalize_name(relation["table"] or "")


def get_base_object(model_name: str) -> str:
    return TECH_SUFFIX_RE.sub("", normalize_name(model_name)).lower()


def split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    index = 0

    while index < len(sql):
        char = sql[index]
        current.append(char)
        if char == "'":
            if in_string and index + 1 < len(sql) and sql[index + 1] == "'":
                current.append(sql[index + 1])
                index += 1
            else:
                in_string = not in_string
        elif char == ";" and not in_string:
            statement = "".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def extract_insert_target(sql: str) -> tuple[str, str]:
    match = INSERT_RE.match(sql.strip())
    if not match:
        return "", sql
    return match.group("table"), match.group("select")


def strip_sql_noise(sql: str) -> str:
    sql = re.sub(r"/\*\+.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n\r]*", "", sql)
    sql = re.sub(r"(?im)^\s*commit\s*;?\s*$", "", sql)
    sql = re.sub(r"(?is)\bcommit\s*;?\s*$", "", sql)
    sql = sql.strip()
    sql = re.sub(r";+\s*$", "", sql)
    return sql.strip()


def clean_oracle_sql(sql: str) -> str:
    return strip_sql_noise(sql)


def extract_target_table(sql: str) -> tuple[str, str]:
    sql = clean_oracle_sql(sql)
    statements = []
    target_table = ""

    for statement in split_statements(sql):
        if COMMIT_RE.match(statement):
            continue
        current_target, current_sql = extract_insert_target(statement)
        if current_target and not target_table:
            target_table = current_target
        statements.append(current_sql.strip())

    return ";\n".join(statements), target_table


def _string_type() -> exp.DataType:
    return exp.DataType.build("TEXT")


def _bigint_type() -> exp.DataType:
    return exp.DataType.build("BIGINT")


def _coalesced_string(expression: exp.Expression) -> exp.Expression:
    return exp.Coalesce(
        this=exp.Cast(this=expression.copy(), to=_string_type()),
        expressions=[exp.Literal.string("")],
    )


def _standard_hash_md5(expression: exp.Expression) -> exp.Expression:
    return exp.Upper(this=exp.MD5(this=_coalesced_string(expression)))


def _decode_to_case(node: exp.Anonymous) -> exp.Expression:
    args = list(node.expressions)
    if len(args) < 3:
        return node

    base = args[0]
    pairs = args[1:]
    default = None
    if len(pairs) % 2 == 1:
        default = pairs.pop()

    case = exp.Case()
    for compare, result in zip(pairs[0::2], pairs[1::2]):
        case = case.when(exp.EQ(this=base.copy(), expression=compare.copy()), result.copy())

    if default is not None:
        case = case.else_(default.copy())
    return case


def _rewrite_trunc(value: exp.Expression, unit: exp.Expression | None = None) -> exp.Expression:
    if unit and isinstance(unit, exp.Literal) and unit.is_string:
        if unit.this.lower() in {"mm", "mon", "month"}:
            return exp.DateTrunc(this=value.copy(), unit=exp.Literal.string("month"))
    return exp.Cast(this=value.copy(), to=exp.DataType.build("DATE"))


def _rewrite_add_months(
    date_value: exp.Expression,
    months: exp.Expression | None,
    original: exp.Expression,
) -> exp.Expression:
    if isinstance(months, exp.Neg) and isinstance(months.this, exp.Literal):
        return exp.Sub(
            this=date_value.copy(),
            expression=exp.Interval(this=months.this.copy(), unit=exp.Var(this="MONTH")),
        )
    if isinstance(months, exp.Literal) and not months.is_string:
        if str(months.this).startswith("-"):
            return exp.Sub(
                this=date_value.copy(),
                expression=exp.Interval(
                    this=exp.Literal.number(str(months.this).lstrip("-")),
                    unit=exp.Var(this="MONTH"),
                ),
            )
        return exp.Add(
            this=date_value.copy(),
            expression=exp.Interval(this=months.copy(), unit=exp.Var(this="MONTH")),
        )
    return original


def apply_oracle_rules(expression: exp.Expression, warnings: list[str]) -> exp.Expression:
    def transform(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.StandardHash):
            algorithm = node.args.get("expression")
            if (
                isinstance(algorithm, exp.Literal)
                and algorithm.is_string
                and algorithm.this.upper() == "MD5"
            ):
                value = (
                    node.this.transform(transform)
                    if isinstance(node.this, exp.Expression)
                    else node.this
                )
                if isinstance(value, exp.Expression):
                    return _standard_hash_md5(value)
            warnings.append("standard_hash with non-MD5 algorithm was left unchanged")
            return node

        if isinstance(node, exp.DPipe):
            left = (
                node.this.transform(transform)
                if isinstance(node.this, exp.Expression)
                else node.this
            )
            right = (
                node.expression.transform(transform)
                if isinstance(node.expression, exp.Expression)
                else node.expression
            )
            expressions: list[exp.Expression] = []
            if isinstance(left, exp.Concat):
                expressions.extend(left.expressions)
            elif isinstance(left, exp.Expression):
                expressions.append(left)
            if isinstance(right, exp.Concat):
                expressions.extend(right.expressions)
            elif isinstance(right, exp.Expression):
                expressions.append(right)
            return exp.Concat(expressions=expressions)

        if isinstance(node, exp.DateTrunc):
            return _rewrite_trunc(node.this, node.args.get("unit"))

        if isinstance(node, exp.AddMonths):
            date_value = (
                node.this.transform(transform)
                if isinstance(node.this, exp.Expression)
                else node.this
            )
            if isinstance(date_value, exp.Expression):
                return _rewrite_add_months(date_value, node.args.get("expression"), node)
            return node

        if isinstance(node, exp.Anonymous):
            name = node.name.lower()
            if name == "decode":
                return _decode_to_case(node)
            if name == "trunc":
                args = list(node.expressions)
                if not args:
                    warnings.append("trunc without arguments was left unchanged")
                    return node
                return _rewrite_trunc(args[0], args[1] if len(args) > 1 else None)
            if name == "add_months":
                args = list(node.expressions)
                if len(args) < 2:
                    warnings.append("add_months without enough arguments was left unchanged")
                    return node
                return _rewrite_add_months(args[0], args[1], node)
            if name == "to_char":
                return exp.Cast(this=node.expressions[0].copy(), to=_string_type())
            if name == "to_number":
                return exp.Cast(this=node.expressions[0].copy(), to=_bigint_type())

        if isinstance(node, exp.Identifier):
            normalized = normalize_name(node.this)
            if normalized != node.this:
                return exp.Identifier(this=normalized.lower(), quoted=False)

        return node

    return expression.transform(transform)


def lower_sql_outside_strings(sql: str) -> str:
    result: list[str] = []
    in_string = False
    index = 0

    while index < len(sql):
        char = sql[index]
        if char == "'":
            result.append(char)
            if in_string and index + 1 < len(sql) and sql[index + 1] == "'":
                result.append(sql[index + 1])
                index += 1
            else:
                in_string = not in_string
        else:
            result.append(char if in_string else char.lower())
        index += 1
    return "".join(result)


def post_clean_sql(sql: str) -> str:
    sql = re.sub(r"date_trunc\('(?:MM|MONTH)',", "date_trunc('month',", sql)
    return sql


def clean_converted_sql(sql: str) -> str:
    return strip_sql_noise(sql)


def detect_oracle_only_constructs(sql: str) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    has_keep = re.search(r"\bkeep\s*\(", sql, flags=re.IGNORECASE | re.DOTALL)
    has_dense_rank = re.search(r"\bdense_rank\b", sql, flags=re.IGNORECASE | re.DOTALL)

    for pattern in ORACLE_UNSUPPORTED_PATTERNS:
        if re.search(pattern["regex"], sql, flags=re.IGNORECASE | re.DOTALL):
            name = pattern["name"]
            seen.add(name)
            suggestion = pattern.get("suggestion", "")
            message = f"{pattern['severity'].upper()}: {pattern['message']}"
            if suggestion:
                message = f"{message} Suggestion: {suggestion}"
            warnings.append(message)

    if has_keep and has_dense_rank and "oracle_keep_dense_rank" not in seen:
        seen.add("oracle_keep_dense_rank")
        warnings.append(
            "ERROR: Oracle KEEP (DENSE_RANK FIRST/LAST ORDER BY ...) is not supported "
            "by StarRocks and requires manual rewrite."
        )

    for construct, regex in ORACLE_ONLY_DETECT_PATTERNS:
        if re.search(regex, sql, flags=re.IGNORECASE | re.DOTALL):
            if construct in {"KEEP", "DENSE_RANK"} and "oracle_keep_dense_rank" in seen:
                continue
            warnings.append(f"Oracle-only construct remains after conversion: {construct}")

    return warnings


def add_oracle_only_warnings(result: ConversionResult) -> None:
    for warning in detect_oracle_only_constructs(result.sql):
        if warning not in result.warnings:
            result.warnings.append(warning)


def convert_oracle_to_starrocks(sql: str) -> ConversionResult:
    result = ConversionResult()
    if not sql.strip():
        return result

    cleaned_sql, target_table = extract_target_table(sql)
    result.target_table = target_table
    if target_table:
        relation = parse_relation_name(target_table)
        result.target_schema = relation["schema"] or ""
        result.model_name = normalize_model_name(target_table)
        result.base_object = get_base_object(result.model_name)
        result.logs.append(f"Target table: {target_table}")
        if result.target_schema:
            result.logs.append(f"Target schema: {result.target_schema}")

    try:
        expressions = sqlglot.parse(cleaned_sql, read="oracle")
        converted = [
            apply_oracle_rules(expression, result.warnings).sql(
                dialect="starrocks",
                pretty=True,
            )
            for expression in expressions
            if expression is not None
        ]
        result.sql = clean_converted_sql(
            post_clean_sql(lower_sql_outside_strings(";\n\n".join(converted)))
        )
        add_oracle_only_warnings(result)
        return result
    except Exception as exc:
        result.sql = clean_converted_sql(f"{cleaned_sql}\n\n/* Conversion error: {exc} */")
        result.warnings.append(f"Conversion error: {exc}")
        add_oracle_only_warnings(result)
        return result


def format_sql(sql: str, dialect: str) -> tuple[str, str | None]:
    if not sql.strip():
        return "", None

    try:
        protected_sql = sql
        placeholders: dict[str, str] = {}
        for index, match in enumerate(JINJA_RE.finditer(sql)):
            placeholder = f"JINJA_PLACEHOLDER_{index}"
            placeholders[placeholder] = match.group(0)
            protected_sql = protected_sql.replace(match.group(0), placeholder, 1)

        expressions = sqlglot.parse(protected_sql, read=dialect)
        formatted_sql = ";\n\n".join(
            expression.sql(dialect=dialect, pretty=True)
            for expression in expressions
            if expression is not None
        )
        for placeholder, jinja in placeholders.items():
            formatted_sql = re.sub(
                rf"[`\"]?{re.escape(placeholder)}[`\"]?",
                jinja,
                formatted_sql,
                flags=re.IGNORECASE,
            )
        return formatted_sql, None
    except Exception as exc:
        return sql, f"Format error: {exc}"
