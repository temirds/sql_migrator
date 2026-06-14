from dataclasses import dataclass, field


DEFAULT_STATUS = "Ready"
DEFAULT_PROJECT_DIR = "../dbt_fs"


@dataclass
class AppState:
    oracle_sql: str = ""
    starrocks_sql: str = ""
    status: str = DEFAULT_STATUS
    project_dir: str = DEFAULT_PROJECT_DIR
    save_dir: str = ""
    target_schema: str = ""
    sql_file_name: str = ""
    yaml_file_name: str = ""
    model_name: str = ""
    base_object: str = ""
    use_empty_dbt_run: bool = False
    warnings: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
