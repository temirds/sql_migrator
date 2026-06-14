# sql_migrator context

## Goal

Local Python UI tool for migrating Oracle SQL to StarRocks/dbt SQL.

The tool is used inside `airflow-repo` next to the dbt project `dbt_fs`.

Main flow:
1. User pastes Oracle SQL into the left editor.
2. User clicks Convert.
3. Converted StarRocks/dbt SQL appears in the right editor.
4. Tool extracts target table from `insert into`.
5. Tool prepares output folder, SQL file name, YAML file name.
6. User can save SQL + YAML.
7. User can run dbt parse.
8. User can run dbt run --empty for the generated model.

## Tech stack

- Python
- NiceGUI
- CodeMirror via `ui.codemirror`
- sqlglot
- pyyaml
- dbt project: `../dbt_fs`

Do not use Streamlit.

## Project structure

```text
airflow-repo/
  dbt_fs/
    dbt_project.yml
    target/
      manifest.json
    models/
      ...
  sql_migrator/
    app.py
    converter.py
    dbt_resolver.py
    file_utils.py
    state.py
    config.yml
    .sql_migrator_state.json
    requirements.txt
    README.md
    context.md
```

## UI decisions

The UI uses a JetBrains Darcula-like dark theme.

Current layout must stay:

1. Two SQL editors on top:

   * left: Oracle SQL
   * right: StarRocks / dbt SQL
2. Action bar below editors:

   * Convert
   * Clear
   * dbt parse
   * Save
   * Save + dbt run
   * compact status chip
3. Output structure block below actions.
4. Warnings and Logs panels below output structure.

Do not change this structure unless explicitly requested.

## SQL editors

* Use `ui.codemirror`.
* Editors must stay side by side.
* Both editors have the same height.
* Right editor is editable.
* No auto-conversion while typing.
* Conversion only runs by button click.
* Format in the right StarRocks / dbt editor must support dbt/Jinja expressions such as `{{ xref(...) }}` without removing or corrupting them.

Each editor has overlay buttons inside the editor:

* copy
* format

Overlay buttons:

* appear on hover;
* are inside the editor area;
* are positioned in the top-right area;
* must not overlap scrollbar;
* should be shifted slightly left from the scrollbar.

## UI style

Theme should look like JetBrains IDE / Darcula.

Preferred colors:

```css
--jb-bg: #2b2d30;
--jb-panel: #1e1f22;
--jb-panel-2: #25262a;
--jb-header: #3c3f41;
--jb-border: #4b4f52;
--jb-border-soft: #3a3d40;
--jb-text: #dfe1e5;
--jb-muted: #a9b0b8;
--jb-muted-2: #7a8088;
--jb-accent: #4e94ce;
--jb-accent-hover: #5aa7e8;
--jb-input: #2f3136;
--jb-editor: #1e1f22;
```

Important UI fixes already requested:

* remove large top status text like `Formatted StarRocks SQL`;
* keep status as small chip in action bar;
* buttons should be compact, not huge blue buttons;
* input labels must not overlap input values;
* Base path label should be separate from input;
* Output structure should look like an IDE file tree;
* Warnings/Logs text must have left/top padding;
* file tree inputs must have right padding and not touch the panel edge.
* Output structure inputs must have left/right internal padding so text does not touch field edges.

## Output structure

Output structure should look like an editable file tree.

Concept:

```text
Output structure

Base path
[ ..\dbt_fs\models ]

 dm_partners_sales
   <> DM_PARTNERS_SALES_P1.sql
   {} _DM_PARTNERS_SALES_MODELS.yml

Will save
SQL:  ..\dbt_fs\models\dm_partners_sales\DM_PARTNERS_SALES_P1.sql
YAML: ..\dbt_fs\models\dm_partners_sales\_DM_PARTNERS_SALES_MODELS.yml
```

Editable fields:

* Base path
* folder name
* SQL file name
* YAML file name

Internal state should still keep:

* project_dir
* base_path
* last_base_path
* folder_name
* sql_file_name
* yaml_file_name
* model_name
* base_object
* target_schema

Base path persistence:

* store the last manually entered Base path in `state.last_base_path`;
* persist it in `sql_migrator/.sql_migrator_state.json` as:
  `{"last_base_path": "../dbt_fs/models/other"}`;
* on app start, use persisted `last_base_path` if present, otherwise default to `../dbt_fs/models`;
* if the persistence file is missing, use default;
* if the persistence file is broken, ignore it, use default, and add warning/log;
* when user edits Base path, update `state.base_path`, update `state.last_base_path`, and save the JSON file immediately;
* Convert must not reset Base path to `../dbt_fs/models`;
* Clear, dbt parse, Save, and Save + dbt run must not change Base path;
* Save paths use `base_path / folder_name`, so `../dbt_fs/models/other` plus `ds_bin_restrictions` saves under `../dbt_fs/models/other/ds_bin_restrictions`.

## Naming rules

If target table is:

```sql
insert into other.dm$partners_sales$p1
```

Then schema `other` must NOT be included in model/folder/yml names.

Correct:

```text
target_schema: other
model_name: DM_PARTNERS_SALES_P1
sql_file_name: DM_PARTNERS_SALES_P1.sql
base_object: dm_partners_sales
folder_name: dm_partners_sales
yaml_file_name: _DM_PARTNERS_SALES_MODELS.yml
```

Schema is stored separately as `target_schema`.

Rules:

* schema.table -> split schema and table;
* model name is built only from table;
* replace special chars with `_`;
* `$`, `#`, `.`, spaces -> `_`;
* collapse multiple `_`;
* strip leading/trailing `_`;
* SQL file name upper case;
* folder name lower case.

Base object removes technical suffixes:

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

Examples:

```text
other.dm$partners_sales$p1
-> model_name: DM_PARTNERS_SALES_P1
-> base_object: dm_partners_sales

ds$bin_restrictions$b
-> model_name: DS_BIN_RESTRICTIONS_B
-> base_object: ds_bin_restrictions

ss.f$intellect_consultant$s
-> model_name: F_INTELLECT_CONSULTANT_S
-> base_object: f_intellect_consultant
```

## YAML generation

YAML file name:

```text
_<BASE_MODEL_NAME>_MODELS.yml
```

YAML model config format must be:

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
* Do not render tags as multiline list.
* There must be one empty line between models.
* `materialized` is always `truncate_insert`.
* `description` is always `''`.
* If YAML already exists:

  * read it;
  * preserve existing models;
  * add new model to the end;
  * if model already exists, update config instead of adding duplicate;
  * never allow two models with the same name.
* If existing YAML has tags, reuse the first tag as schema tag.
* If not, use `target_schema.upper()` or `"OTHER"`.

## dbt command behavior

Buttons:

* `dbt parse`
* `Save + dbt run`

There is no `Use --empty` checkbox in the UI.

For all dbt commands, logs must include:

* cwd;
* command args;
* command text;
* return code;
* stdout;
* stderr;
* error if any.

dbt commands in NiceGUI button handlers must run through async subprocess APIs.
Do not call blocking `subprocess.run` from UI event handlers, because it blocks the NiceGUI event loop and causes `Connection lost. Trying to reconnect...`.

If dbt executable is not found:
show clear message:

```text
dbt executable not found. Check that dbt is installed and available in PATH.
```

Also log current PATH.

`Save + dbt run`:

* always runs:
  `dbt run --select <model_name> --empty`
* if state still has `use_empty`, it may remain internally, but UI behavior must always treat it as enabled.

## Oracle to StarRocks conversion rules

Base conversion uses sqlglot:

* read dialect: oracle
* write dialect: starrocks
* pretty=True

Pre/post rules:

* remove Oracle hints `/*+ ... */`;
* remove `commit`;
* remove `insert into <target_table>` from result SQL;
* `sysdate` -> `current_timestamp`;
* `nvl(...)` -> `coalesce(...)`;
* `standard_hash(x, 'MD5')` -> `upper(md5(coalesce(cast(x as string), '')))`;
* nested `standard_hash` should be handled;
* Oracle `||` -> `concat(...)`;
* `trunc(date)` -> `cast(date as date)`;
* `trunc(date, 'mm')` -> `date_trunc('month', date)`;
* `add_months(date, -n)` -> `date - interval n month`;
* `to_char(x)` -> `cast(x as string)`;
* `to_number(x)` -> `cast(x as bigint)`;
* `decode(...)` -> `case when ...`.

If sqlglot fails:

* UI must not crash;
* show readable error in result SQL or warnings;
* keep best-effort converted SQL.

## dbt resolver / xref rules

Need to replace physical tables with dbt `xref` using `target/manifest.json`.

Important context:

Oracle physical table example:

```sql
DWH_STAGE2.S01#Z_CLIENT
```

In StarRocks/source it is often:

```text
S01.Z_CLIENT
```

In dbt staging it is usually:

```text
DWH_STAGE.STG__S01_Z_CLIENT
```

Therefore:

If Oracle schema is `DWH_STAGE2`:

1. Normalize table name:
   `S01#Z_CLIENT` -> `S01_Z_CLIENT`
2. Build preferred model:
   `STG__S01_Z_CLIENT`
3. Search manifest for this model first.
4. If found, replace with:

```sql
{{ xref('STG__S01_Z_CLIENT', 'DWH_STAGE') }}
```

For schemas `OTHER` and `SS`:

* search manifest normally;
* if model found, replace with:

```sql
{{ xref('<MODEL_NAME>', 'PROD') }}
```

General xref schema rule:

* if model name starts with `STG__` -> `DWH_STAGE`;
* else -> `PROD`.

If table cannot be resolved:

* keep physical table as-is;
* add warning:
  `unresolved table: <schema.table>`;
* status chip should become warning/error style;
* warning panel should list unresolved tables.

If source is found but model/xref is not found:

* do not silently replace with source unless explicitly configured;
* add warning:
  `source found but model/xref not found: <table>`.

Use placeholders for Jinja:

* SQLGlot may quote Jinja incorrectly.
* Use placeholders like `__XREF_0__`, then replace after SQL generation with:
  `{{ xref('MODEL', 'SCHEMA') }}`.

## Warnings and visual error state

If conversion has warnings:

* show warnings in Warnings panel;
* status chip text:
  `Converted with warnings`
* status chip style should be reddish/warning, not huge banner.

If no warnings:

* status chip:
  `Converted`

## Test SQL

Use this test SQL:

```sql
insert /*+ append enable_parallel_dml parallel(20) */
into other.dm$partners_sales$p1
select
    sysdate as s$change_date,
    standard_hash(
        standard_hash(t.org_bin, 'MD5') ||
        standard_hash(t.client_id, 'MD5') ||
        standard_hash(t.sale_month, 'MD5') ||
        standard_hash(t.total_amount, 'MD5') ||
        standard_hash(t.sale_type_name, 'MD5'),
        'MD5'
    ) as s$md5,
    t.org_bin,
    t.client_id,
    t.sale_month,
    t.sale_day,
    t.sale_type_name,
    t.total_amount,
    t.operation_cnt,
    t.last_operation_date,
    t.rn
from (
    select
        nvl(org.c_inn, 'N/A') as org_bin,
        cl.id as client_id,
        trunc(op.order_regdate, 'mm') as sale_month,
        trunc(op.order_regdate) as sale_day,
        decode(
            op.sale_type,
            'KaspiRed', 'RED',
            'KaspiKredit', 'CREDIT',
            'KaspiKzPayment', 'PAYMENT',
            'OTHER'
        ) as sale_type_name,
        sum(nvl(op.amount, 0)) as total_amount,
        count(*) as operation_cnt,
        max(op.order_regdate) as last_operation_date,
        row_number() over (
            partition by org.c_inn, trunc(op.order_regdate, 'mm')
            order by max(op.order_regdate) desc
        ) as rn
    from DWH_STAGE2.S01#Z_CLIENT org
        join DWH_STAGE2.S0090$KB_OPERATION op
            on op.org_id = org.id
        left join SS.D$RFO_CLIENT_FL cl
            on cl.bin = org.c_inn
           and cl.s$end = date '3000-01-01'
    where op.order_regdate >= add_months(trunc(sysdate, 'mm'), -3)
      and op.order_regdate < trunc(sysdate)
      and nvl(org.class_id, 'N') = 'CL_ORG'
      and op.status = 'SUCCESS'
      and org.c_inn is not null
    group by
        nvl(org.c_inn, 'N/A'),
        cl.id,
        trunc(op.order_regdate, 'mm'),
        trunc(op.order_regdate),
        decode(
            op.sale_type,
            'KaspiRed', 'RED',
            'KaspiKredit', 'CREDIT',
            'KaspiKzPayment', 'PAYMENT',
            'OTHER'
        )
) t
where t.rn = 1;

commit;
```

Expected:

* target table recognized:
  `other.dm$partners_sales$p1`;
* target_schema:
  `other`;
* model_name:
  `DM_PARTNERS_SALES_P1`;
* base_object:
  `dm_partners_sales`;
* SQL file:
  `DM_PARTNERS_SALES_P1.sql`;
* YAML file:
  `_DM_PARTNERS_SALES_MODELS.yml`;
* save dir:
  `<project_dir>/models/dm_partners_sales`;
* `insert into` removed;
* hint removed;
* `commit` removed;
* `sysdate` replaced;
* `standard_hash` replaced;
* `nvl` replaced;
* `trunc(..., 'mm')` replaced;
* `add_months(..., -3)` replaced;
* `DWH_STAGE2.S01#Z_CLIENT` tries `xref('STG__S01_Z_CLIENT', 'DWH_STAGE')`;
* unresolved tables appear in Warnings.

## Work style

* Keep answers short.
* Show only changed files.
* Do not rewrite unrelated code.
* Always update `context.md`.
* If something is ambiguous, add warning instead of guessing silently.
