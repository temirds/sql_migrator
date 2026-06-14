# SQL Migrator

Local NiceGUI tool for Oracle SQL to StarRocks/dbt SQL migration.

## Run

```bash
pip install -r sql_migrator/requirements.txt
python sql_migrator/app.py
```

## Features

- Two side-by-side SQL editors with hover copy/format actions.
- Manual Oracle SQL to StarRocks/dbt SQL conversion.
- `insert into` target detection and removal.
- Basic Oracle cleanup: hints, `commit`, empty statements.
- Basic Oracle rules: `sysdate`, `nvl`, `standard_hash(..., 'MD5')`, `||`, `trunc`, `add_months`, `to_char`, `to_number`, `decode`.
- File field generation from target table.
- Save SQL and YAML model file.
- Run `dbt parse`.
- Save and run `dbt run --select <model_name>`.

## Config

See `sql_migrator/config.yml`.
