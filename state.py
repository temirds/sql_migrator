from dataclasses import dataclass, field
import json
from pathlib import Path


DEFAULT_STATUS = "Ready"
PERSISTENT_STATE_PATH = Path(__file__).resolve().parent / ".sql_migrator_state.json"


def get_default_project_dir() -> Path:
    sql_migrator_dir = Path(__file__).resolve().parent
    repo_root = sql_migrator_dir.parent
    return repo_root / "dbt_fs"


DEFAULT_PROJECT_DIR = str(get_default_project_dir())


def load_persistent_state() -> tuple[dict, str | None]:
    if not PERSISTENT_STATE_PATH.exists():
        return {}, None

    try:
        loaded = json.loads(PERSISTENT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"Ignored broken persistent state: {exc}"

    if not isinstance(loaded, dict):
        return {}, "Ignored broken persistent state: root value is not an object"
    return loaded, None


def save_persistent_state(data: dict) -> None:
    PERSISTENT_STATE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
    base_path: str = ""
    last_base_path: str = ""
    use_empty_dbt_run: bool = False
    warnings: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
