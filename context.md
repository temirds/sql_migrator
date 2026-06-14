# SQL Migrator context

## Project structure

Проект расположен внутри `airflow-repo`.

Ожидаемая структура:

```text
airflow-repo/
  dbt_fs/
    dbt_project.yml
    target/manifest.json
    models/
  sql_migrator/
    app.py
    converter.py
    dbt_resolver.py
    file_utils.py
    state.py
    command_runner.py
    config.yml
    requirements.txt
    self_check.py
    tests/
    context.md
```

`sql_migrator` и `dbt_fs` находятся на одном уровне.

Нельзя хардкодить абсолютный путь пользователя.

Правильный default `project_dir`:

```python
Path(__file__).resolve().parent.parent / "dbt_fs"
```

Default `base_path`:

```python
project_dir / "models"
```

Если пользователь вручную менял `base_path`, использовать сохранённый `last_base_path`.

---

## UI context

UI написан на NiceGUI.

Основной layout:

1. Верхняя зона: два SQL editor side-by-side.

   * left: Oracle SQL
   * right: StarRocks / dbt SQL
2. Action bar:

   * Convert
   * Clear
   * dbt parse
   * Save
   * Save + dbt run
   * status chip
3. Output structure
4. Warnings
5. Logs

`Use --empty` checkbox удалён.
`dbt run` всегда запускается с `--empty`.

Кнопка `Save + dbt run` всегда должна выполнять:

```bash
dbt run --select <MODEL_NAME> --empty
```

UI стиль:

* тёмный JetBrains/Darcula-like;
* без больших синих uppercase кнопок;
* status должен быть compact chip;
* Warnings/Logs должны иметь ограничение по высоте примерно 50 строк и внутренний scroll;
* новые logs/warnings должны появляться сверху, latest first;
* editor overlay buttons copy/format должны быть внутри editor top-right, но не перекрывать scrollbar.

---

## Base path persistence

Проблема была: после Convert base path сбрасывался на `dbt_fs/models`.

Правильное поведение:

* Convert НЕ меняет base_path.
* Clear НЕ меняет base_path.
* Save НЕ меняет base_path.
* dbt parse/run НЕ меняют base_path.
* Только ручное изменение Base path обновляет `last_base_path`.

Persistent state file:

```text
sql_migrator/.sql_migrator_state.json
```

Формат:

```json
{
  "last_base_path": "../dbt_fs/models/other"
}
```

Если файл отсутствует, использовать default.

Если файл битый, игнорировать и логировать warning.

---

## Naming rules

Если target table содержит schema, schema хранится отдельно и НЕ входит в model/folder/yml names.

Пример:

```text
other.dm$partners_sales$p1
```

Ожидаемо:

```text
target_schema: other
model_name: DM_PARTNERS_SALES_P1
base_object: dm_partners_sales
folder_name: dm_partners_sales
sql_file_name: DM_PARTNERS_SALES_P1.sql
yaml_file_name: _DM_PARTNERS_SALES_MODELS.yml
```

Пример:

```text
ds$bin_restrictions$b
```

Ожидаемо:

```text
target_schema: None
model_name: DS_BIN_RESTRICTIONS_B
base_object: ds_bin_restrictions
folder_name: ds_bin_restrictions
sql_file_name: DS_BIN_RESTRICTIONS_B.sql
yaml_file_name: _DS_BIN_RESTRICTIONS_MODELS.yml
```

Normalize rules:

* `$`, `#`, `.`, spaces, special chars -> `_`
* collapse multiple `_`
* trim `_`
* model/sql file upper case
* folder/base lower case

Base object suffix removal:

* `_P`
* `_P1`
* `_P3_1`
* `_B`
* `_B1`
* `_G`
* `_G1`
* `_S`
* `_T`
* `_TMP`

---

## YAML rules

YAML file:

```text
_<BASE_OBJECT_UPPER>_MODELS.yml
```

Expected format:

```yaml
version: 2

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
```

Rules:

* `tags` must be inline:
  `tags: ["OTHER", "DM_PARTNERS_SALES"]`
* `materialized: truncate_insert`
* `description: ''`
* one blank line between model entries
* if YAML exists, preserve existing models/order
* if model already exists, update it, do not duplicate
* if adding new model, append to end
* if existing YAML has tags, reuse first tag as schema tag
* second tag is always base model name
* if no existing tags, first tag is `target_schema.upper()` or `"OTHER"`

---

## Converter rules

Input can be Oracle SQL / PLSQL fragment.

Converter must:

* extract target table from `insert into <target>`;
* remove `insert into ...`;
* remove Oracle hints;
* remove comments;
* remove `commit`;
* remove trailing semicolon;
* convert Oracle SQL to StarRocks/dbt SQL as much as possible;
* preserve warnings for unsupported parts;
* never silently output known invalid StarRocks SQL as success.

Required replacements:

* `sysdate` -> `current_timestamp`
* `nvl(...)` -> `coalesce(...)`
* `standard_hash(x, 'MD5')` -> `upper(md5(coalesce(cast(x as string), '')))`, including nested cases
* Oracle `||` -> `concat(...)`
* `trunc(date)` -> `cast(date as date)`
* `trunc(date, 'mm')` -> `date_trunc('month', date)`
* `add_months(date, -n)` -> `date - interval n month`
* `to_char(x)` -> `cast(x as string)`
* `to_number(x)` -> `cast(x as bigint)`
* `decode(...)` -> `case when ...`
* aliases/columns with `$` normalized to `_`, for example `s$md5` -> `s_md5`

Cleanup must happen before returning `ConversionResult`.

Preferred function names:

* `clean_oracle_sql`
* `clean_converted_sql`
* `extract_target_table`
* `convert_oracle_to_starrocks`

Avoid unclear names like:

* `final_cleanup_sql`
* `do_cleanup`
* `fix_sql`

---

## Unsupported Oracle syntax policy

`sqlglot` can leave Oracle-only syntax unchanged. This is dangerous.

The converter must detect unsupported Oracle-specific constructs after conversion and add warnings/errors.

Minimum detector list:

* `KEEP (`
* `DENSE_RANK`
* `CONNECT BY`
* `START WITH`
* `ROWNUM`
* `NVL(`
* `SYSDATE`
* `SYSTIMESTAMP`
* `DECODE(`
* `MINUS`
* `DUAL`
* `TO_DATE(`
* `TO_CHAR(`
* `TO_NUMBER(`
* `ADD_MONTHS(`
* `TRUNC(`

Important example:

Oracle:

```sql
replace(max(brand) keep(dense_rank last order by tt.updated), ' ')
```

This is NOT valid StarRocks SQL if left as:

```sql
replace(
  max(brand) keep (
    dense_rank
    last
    order by tt.updated
  ),
  ' '
)
```

Policy:

* default strategy for Oracle `KEEP (DENSE_RANK FIRST/LAST ORDER BY ...)` is warning/manual rewrite;
* do not silently claim success;
* do not generate invalid StarRocks SQL without warning;
* automatic rewrite is optional only if safely implemented and tested;
* partial invalid conversion is worse than explicit warning.

Suggested warning:

```text
Unsupported Oracle KEEP aggregate detected. Manual rewrite required.
```

---

## dbt resolver rules

Resolver must use raw Oracle table references before normalization.

Critical rule:
`DWH_STAGE2` is NOT a real StarRocks/source schema.

For DWH_STAGE2:

```text
DWH_STAGE2.<SRC_SCHEMA>$<TABLE>
-> <SRC_SCHEMA>.<TABLE>
-> preferred model STG__<SRC_SCHEMA>_<TABLE>
-> if STG exists, xref('STG__<SRC_SCHEMA>_<TABLE>', 'DWH_STAGE')
-> else source('<SRC_SCHEMA>', '<TABLE>') if source exists
-> else physical fallback <SRC_SCHEMA>.<TABLE> + warning
```

Same logic for `#`:

```text
DWH_STAGE2.<SRC_SCHEMA>#<TABLE>
-> <SRC_SCHEMA>.<TABLE>
```

Examples:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
```

Means:

```text
StarRocks physical: S0090.TRADEPOINT_ONL_HISTORY
preferred model: STG__S0090_TRADEPOINT_ONL_HISTORY
source fallback: source('S0090', 'TRADEPOINT_ONL_HISTORY')
```

Example:

```text
DWH_STAGE2.S01#Z_CLIENT
```

Means:

```text
StarRocks physical: S01.Z_CLIENT
preferred model: STG__S01_Z_CLIENT
source fallback: source('S01', 'Z_CLIENT')
```

Resolver order:

1. manual overrides
2. DWH_STAGE2 preferred STG__ model
3. DWH_STAGE2 source fallback
4. DWH_STAGE2 physical fallback + warning
5. normal exact model match
6. normal source match
7. unresolved warning

Strict matching:

* only exact normalized match
* case-insensitive exact match allowed
* name/alias/identifier exact normalized match allowed

Forbidden:

* partial match
* startswith
* contains
* fuzzy match
* prefix match

This is forbidden:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
-> xref('STG__S0090_TRADEPOINT_ONL', 'DWH_STAGE')
```

because:

```text
TRADEPOINT_ONL != TRADEPOINT_ONL_HISTORY
```

The resolver must prefer unresolved/physical fallback over a wrong partial match.

---

## Raw table reference preservation

The converter must not lose raw table references before resolver.

Bad:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
-> dwh_stage2.s0090_tradepoint_onl_history
```

before resolver.

Good:
resolver receives:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
DWH_STAGE2.S01#Z_CLIENT
```

If sqlglot normalizes/destroys `$` or `#`, use raw SQL pre-scan before sqlglot.

Possible regex:

```python
TABLE_REF_RE = re.compile(
    r"(?i)\b(from|join|update|into|merge\s+into)\s+([a-zA-Z0-9_$#]+(?:\.[a-zA-Z0-9_$#]+)?)"
)
```

Target table from INSERT INTO should be extracted, but not resolver-replaced as source.

---

## Correct resolver logs

Logs should show diagnostics like:

```text
resolver input raw: DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
parsed DWH_STAGE2:
  source_schema: S0090
  source_table: TRADEPOINT_ONL_HISTORY
  preferred_model: STG__S0090_TRADEPOINT_ONL_HISTORY
model lookup:
  candidate: STG__S0090_TRADEPOINT_ONL_HISTORY
  found: false
source lookup:
  source_schema: S0090
  source_table: TRADEPOINT_ONL_HISTORY
  found: true
resolved:
  DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY -> source('S0090', 'TRADEPOINT_ONL_HISTORY')
```

These wrong logs must not appear:

```text
resolved table dwh_stage2.s0090_tradepoint_onl_history -> dwh_stage2.s0090_tradepoint_onl_history
resolved table dwh_stage2.s0090_tradepoint_onl -> xref('STG__S0090_TRADEPOINT_ONL', 'DWH_STAGE')
resolved table s01.z_client -> s01.z_client
```

Correct examples:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY -> xref('STG__S0090_TRADEPOINT_ONL_HISTORY', 'DWH_STAGE')
```

or:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY -> source('S0090', 'TRADEPOINT_ONL_HISTORY')
```

and:

```text
DWH_STAGE2.S01#Z_CLIENT -> xref('STG__S01_Z_CLIENT', 'DWH_STAGE')
```

or:

```text
DWH_STAGE2.S01#Z_CLIENT -> source('S01', 'Z_CLIENT')
```

---

## dbt command runner

On Windows, `asyncio.create_subprocess_shell` failed with:

```text
NotImplementedError
```

Therefore do not use:

* `asyncio.create_subprocess_shell`
* `asyncio.create_subprocess_exec`

Use blocking `subprocess.run`, but execute it in a separate thread:

```python
async def run_command_in_thread(...):
    return await asyncio.to_thread(...)
```

dbt command runner:

* uses `subprocess.run(..., shell=True, cwd=project_dir)`
* captures stdout/stderr/return_code/error
* logs full exception details:

  * type
  * str
  * repr
  * traceback

dbt parse:

```bash
dbt parse
```

dbt run:

```bash
dbt run --select <MODEL_NAME> --empty
```

Logs before run:

* project_dir
* cwd
* command text
* python executable
* platform
* PATH
* started

Logs after run:

* return code
* stdout
* stderr
* error

UI must not show `Connection lost`.

---

## Test requirements

Tests should exist under:

```text
sql_migrator/tests/
```

Expected test areas:

### Converter

* removes Oracle hints
* removes comments
* removes commit
* removes trailing semicolon
* removes insert into
* extracts target table
* target schema handled separately
* schema not included in model_name
* detects unsupported Oracle syntax
* detects Oracle KEEP aggregate

### Resolver

* DWH_STAGE2 `$` works
* DWH_STAGE2 `#` works
* STG__ lookup has priority
* source fallback works
* partial match forbidden
* physical fallback correct
* `dwh_stage2.*` does not remain in output for DWH_STAGE2 mapping

### YAML

* inline tags
* no duplicate models
* existing models preserved
* new model appended
* stable formatting

### File utils

* `ds$bin_restrictions$b` -> `DS_BIN_RESTRICTIONS_B`
* `other.dm$partners_sales$p1` -> schema `other`, model `DM_PARTNERS_SALES_P1`, base `dm_partners_sales`

### Command runner

* uses `asyncio.to_thread`
* does not use async subprocess
* returns stdout/stderr/return_code/error
* does not crash on failed command

### State

* last_base_path persists
* Convert does not reset base_path
* Clear does not reset base_path

---

## Self-check

There should be:

```text
sql_migrator/self_check.py
```

It should run key checks without UI and print PASS/FAIL.

Required checks:

* clean_oracle_sql
* clean_converted_sql
* target extraction
* DWH_STAGE2 dollar resolver
* DWH_STAGE2 hash resolver
* no partial match
* yaml rendering
* base_path persistence
* detects Oracle KEEP aggregate
* does not silently accept Oracle KEEP
* normal SQL has no unsupported warnings

If any check fails:

* exit code 1

Before saying work is done, run:

```bash
pytest sql_migrator/tests
python sql_migrator/self_check.py
python -m compileall sql_migrator
```

If checks fail, do not claim success.

---

## Refactoring policy

Keep code simple.

Preferred module responsibilities:

```text
converter.py
- clean Oracle SQL
- extract target table
- convert Oracle to StarRocks/dbt SQL
- apply resolver replacements
- clean converted SQL
- detect unsupported Oracle constructs

dbt_resolver.py
- read manifest
- index models
- index sources
- resolve physical table references
- parse DWH_STAGE2 references

file_utils.py
- normalize names
- build model_name/base_object/file names
- paths

state.py
- runtime state
- persistent last_base_path

command_runner.py
- dbt parse/dbt run subprocess/thread execution

app.py
- UI only
- handlers
- state updates
```

Avoid:

* giant functions
* duplicate regex logic
* unclear names
* unused old async subprocess code
* old `use_empty`
* heavy business logic inside app.py
* funny comments
* misleading TODO comments

Prefer clear names:

* `clean_oracle_sql`
* `clean_converted_sql`
* `extract_target_table`
* `convert_oracle_to_starrocks`
* `resolve_table_reference`
* `parse_dwh_stage2_reference`
* `run_dbt_command`
* `run_command_in_thread`

Avoid unclear names:

* `final_cleanup_sql`
* `fix_sql`
* `do_cleanup`
* `res`
* `tmp`
* `x`
* `data2`

---

## Current key bug history

Bugs that must not return:

1. dbt parse/run caused NiceGUI `Connection lost`.
2. Windows async subprocess raised `NotImplementedError`.
3. Base path reset to `dbt_fs/models` after Convert.
4. `Use --empty` checkbox existed, but it should be always enabled and hidden.
5. Resolver lost raw DWH_STAGE2 references.
6. Resolver matched partial model `STG__S0090_TRADEPOINT_ONL` for `TRADEPOINT_ONL_HISTORY`.
7. Resolver left `dwh_stage2.s0090_tradepoint_onl_history`.
8. Resolver left `s01.z_client` instead of using raw `DWH_STAGE2.S01#Z_CLIENT`.
9. Comments/hints/commit/trailing semicolon returned after resolver changes.
10. Oracle KEEP aggregate was silently left as invalid StarRocks SQL.
11. Logs/Warnigns grew downward too far; latest logs should appear at top and panels should scroll internally.

---

## Golden examples

### Example 1

Input target:

```text
DS$BIN_RESTRICTIONS$P
```

Expected:

```text
model_name: DS_BIN_RESTRICTIONS_P
base_object: ds_bin_restrictions
folder_name: ds_bin_restrictions
sql_file_name: DS_BIN_RESTRICTIONS_P.sql
yaml_file_name: _DS_BIN_RESTRICTIONS_MODELS.yml
```

### Example 2

Raw source:

```text
DWH_STAGE2.S0090$TRADEPOINT_ONL_HISTORY
```

Expected resolver:

```text
preferred model: STG__S0090_TRADEPOINT_ONL_HISTORY
source fallback: source('S0090', 'TRADEPOINT_ONL_HISTORY')
physical fallback: S0090.TRADEPOINT_ONL_HISTORY
```

Never:

```text
dwh_stage2.s0090_tradepoint_onl_history
STG__S0090_TRADEPOINT_ONL
```

### Example 3

Raw source:

```text
DWH_STAGE2.S01#Z_CLIENT
```

Expected resolver:

```text
preferred model: STG__S01_Z_CLIENT
source fallback: source('S01', 'Z_CLIENT')
physical fallback: S01.Z_CLIENT
```

Never:

```text
s01.z_client
```

### Example 4

Oracle cleanup input:

```sql
insert /*+ append enable_parallel_dml parallel(20) */
into DS$BIN_RESTRICTIONS$P
select *
from DWH_STAGE2.S01#Z_CLIENT;

commit;
```

Expected converted SQL:

* no `insert into`
* no `/*+`
* no comments
* no `commit`
* no trailing `;`

### Example 5

Unsupported Oracle KEEP:

```sql
replace(max(brand) keep(dense_rank last order by tt.updated), ' ')
```

Expected:

* warning/error about unsupported Oracle KEEP aggregate
* no silent success
* no claim that SQL is fully valid StarRocks

---

## Final instruction

Only update `sql_migrator/context.md`.

Do not change code in this task.
Do not refactor in this task.
Do not run dbt in this task.
