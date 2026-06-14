from __future__ import annotations

from pathlib import Path

import state


def test_default_project_dir_is_sibling_dbt_fs() -> None:
    assert state.get_default_project_dir() == Path(state.__file__).resolve().parent.parent / "dbt_fs"


def test_last_base_path_persistence(tmp_path: Path, monkeypatch) -> None:
    persistent_path = tmp_path / ".sql_migrator_state.json"
    monkeypatch.setattr(state, "PERSISTENT_STATE_PATH", persistent_path)

    state.save_persistent_state({"last_base_path": "../dbt_fs/models/other"})
    loaded, warning = state.load_persistent_state()

    assert warning is None
    assert loaded == {"last_base_path": "../dbt_fs/models/other"}


def test_broken_persistent_state_returns_warning(tmp_path: Path, monkeypatch) -> None:
    persistent_path = tmp_path / ".sql_migrator_state.json"
    persistent_path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(state, "PERSISTENT_STATE_PATH", persistent_path)

    loaded, warning = state.load_persistent_state()

    assert loaded == {}
    assert warning
