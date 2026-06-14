from __future__ import annotations

from pathlib import Path

from nicegui import ui

from command_utils import format_command_log, format_command_start_log, run_shell_command_async
from converter import convert_oracle_to_starrocks, format_sql
from dbt_resolver import load_config, resolve_tables
from file_utils import build_file_fields, resolve_path, save_model_files
from state import (
    AppState,
    DEFAULT_STATUS,
    get_default_project_dir,
    load_persistent_state,
    save_persistent_state,
)


state = AppState()
config = load_config()
state.project_dir = str(config.get("project_dir") or get_default_project_dir())
default_base_path = str(resolve_path(state.project_dir) / "models")
persistent_state, persistent_warning = load_persistent_state()
state.last_base_path = str(persistent_state.get("last_base_path") or default_base_path)
state.base_path = state.last_base_path
state.folder_name = ""
if persistent_warning:
    state.warnings.append(persistent_warning)
    state.logs.append(persistent_warning)


def set_value(element, value: str) -> None:
    if hasattr(element, "set_value"):
        element.set_value(value)
    else:
        element.value = value


def set_status(text: str, level: str = "normal") -> None:
    state.status = text
    status_label.text = text
    status_label.classes(remove="status-warning status-error")
    if level == "warning":
        status_label.classes("status-warning")
    elif level == "error":
        status_label.classes("status-error")


def refresh_logs() -> None:
    warnings_text = "\n".join(f"- {warning}" for warning in state.warnings) or "No warnings"
    logs_text = "\n".join(state.logs) or "No logs"
    set_value(warnings_area, warnings_text)
    set_value(logs_area, logs_text)


def dbt_command_text(args: list[str]) -> str:
    return "dbt " + " ".join(args)


def dbt_project_dir() -> Path:
    return resolve_path(state.project_dir)


async def run_dbt_async(command_text: str, cwd: Path) -> tuple[int | None, str]:
    result = await run_shell_command_async(command_text, cwd)
    return result.return_code, format_command_log(result)


def full_save_dir() -> str:
    return str(Path(state.base_path) / state.folder_name)


def output_path(file_name: str) -> str:
    if not state.base_path or not state.folder_name or not file_name:
        return "-"
    return str(Path(state.base_path) / state.folder_name / file_name)


def refresh_output_paths() -> None:
    sql_path_label.text = f"SQL: {output_path(state.sql_file_name)}"
    yaml_path_label.text = f"YAML: {output_path(state.yaml_file_name)}"


def refresh_file_fields() -> None:
    set_value(base_path_input, state.base_path)
    set_value(folder_input, state.folder_name)
    set_value(sql_file_input, state.sql_file_name)
    set_value(yaml_file_input, state.yaml_file_name)
    refresh_output_paths()


def update_oracle_sql(event) -> None:
    state.oracle_sql = event.value or ""
    set_status(DEFAULT_STATUS)


def update_starrocks_sql(event) -> None:
    state.starrocks_sql = event.value or ""


def update_base_path(event) -> None:
    state.base_path = event.value or ""
    state.last_base_path = state.base_path
    save_persistent_state({"last_base_path": state.last_base_path})
    refresh_output_paths()


def update_folder_name(event) -> None:
    state.folder_name = event.value or ""
    state.base_object = state.folder_name
    refresh_output_paths()


def update_sql_file_name(event) -> None:
    state.sql_file_name = event.value or ""
    refresh_output_paths()


def update_yaml_file_name(event) -> None:
    state.yaml_file_name = event.value or ""
    refresh_output_paths()


def convert_sql() -> None:
    result = convert_oracle_to_starrocks(state.oracle_sql)
    resolved = resolve_tables(result.sql, state.project_dir, config)

    state.starrocks_sql = resolved.sql
    state.warnings = [*result.warnings, *resolved.warnings]
    state.logs = [*result.logs, *resolved.logs]
    state.target_schema = result.target_schema
    state.model_name = result.model_name
    state.base_object = result.base_object

    if result.target_table:
        fields = build_file_fields(state.project_dir, result.target_table)
        state.model_name = fields["model_name"]
        state.base_object = fields["base_object"]
        state.folder_name = state.base_object
        state.sql_file_name = fields["sql_file_name"]
        state.yaml_file_name = fields["yaml_file_name"]
        state.save_dir = full_save_dir()
        if state.warnings:
            set_status("Conversion completed with warnings", "warning")
        else:
            set_status("Converted")
    else:
        state.warnings.append("Target table not found")
        set_status("Conversion completed with warnings", "warning")

    set_value(starrocks_editor, state.starrocks_sql)
    refresh_file_fields()
    refresh_logs()


def clear_all() -> None:
    state.oracle_sql = ""
    state.starrocks_sql = ""
    state.warnings = []
    state.logs = []
    set_value(oracle_editor, "")
    set_value(starrocks_editor, "")
    refresh_logs()
    set_status(DEFAULT_STATUS)


def copy_oracle_sql() -> None:
    ui.clipboard.write(state.oracle_sql)
    set_status("Copied Oracle SQL")


def copy_starrocks_sql() -> None:
    ui.clipboard.write(state.starrocks_sql)
    set_status("Copied StarRocks SQL")


def format_oracle_sql() -> None:
    formatted_sql, error = format_sql(state.oracle_sql, "oracle")
    if error:
        set_status(error)
        return
    state.oracle_sql = formatted_sql
    set_value(oracle_editor, formatted_sql)
    set_status("Formatted Oracle SQL")


def format_starrocks_sql() -> None:
    state.starrocks_sql = getattr(starrocks_editor, "value", state.starrocks_sql) or ""
    formatted_sql, error = format_sql(state.starrocks_sql, "starrocks")
    if error:
        set_status(error)
        return
    state.starrocks_sql = formatted_sql
    set_value(starrocks_editor, formatted_sql)
    set_status("Formatted StarRocks SQL")


def save_files() -> bool:
    try:
        logs, warnings = save_model_files(
            sql=state.starrocks_sql,
            save_dir=full_save_dir(),
            sql_file_name=state.sql_file_name,
            yaml_file_name=state.yaml_file_name,
            model_name=state.model_name,
            target_schema=state.target_schema,
        )
        state.logs.extend(logs)
        state.warnings.extend(warnings)
        refresh_logs()
        set_status("Saved")
        return True
    except Exception as exc:
        state.warnings.append(f"Save error: {exc}")
        refresh_logs()
        set_status("Save failed")
        return False


async def dbt_parse() -> None:
    set_status("Running dbt parse...")
    command_text = dbt_command_text(["parse"])
    cwd = dbt_project_dir()
    state.logs.append(format_command_start_log(command_text, cwd))
    refresh_logs()
    code, output = await run_dbt_async(command_text, cwd)
    state.logs.append(output)
    refresh_logs()
    if code == 0:
        set_status("dbt parse finished")
    else:
        set_status("dbt parse failed", "error")


async def save_and_dbt_run() -> None:
    if not save_files():
        return
    set_status("Running dbt run...")
    state.use_empty_dbt_run = True
    args = ["run", "--select", state.model_name, "--empty"]
    command_text = dbt_command_text(args)
    cwd = dbt_project_dir()
    state.logs.append(format_command_start_log(command_text, cwd))
    refresh_logs()
    code, output = await run_dbt_async(command_text, cwd)
    state.logs.append(output)
    refresh_logs()
    if code == 0:
        set_status("dbt run finished")
    else:
        set_status("dbt run failed", "error")


ui.page_title("SQL Migrator")
ui.dark_mode().enable()

ui.add_css(
    """
    :root {
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
        --jb-danger: #cf6679;
        --jb-success: #6aab73;
        --jb-input: #2f3136;
        --jb-input-hover: #35383d;
        --jb-editor: #1e1f22;
    }

    html,
    body {
        background: var(--jb-bg) !important;
        color: var(--jb-text) !important;
        font-size: 14px;
    }

    #app,
    .nicegui-content,
    .q-layout,
    .q-page,
    .q-page-container {
        background: var(--jb-bg) !important;
        color: var(--jb-text) !important;
    }

    .app-title {
        color: var(--jb-text);
        letter-spacing: 0;
    }

    .editor-panel,
    .soft-panel {
        background: var(--jb-panel);
        border: 1px solid var(--jb-border-soft);
        border-radius: 8px;
        overflow: hidden;
    }

    .editor-titlebar {
        height: 34px;
        background: var(--jb-header);
        border-bottom: 1px solid var(--jb-border);
        color: var(--jb-text);
        padding: 0 12px;
        font-size: 13px;
        font-weight: 600;
    }

    .editor-wrapper {
        position: relative;
        width: 100%;
    }

    .editor-actions {
        position: absolute;
        top: 6px;
        right: 34px;
        z-index: 20;
        display: flex;
        gap: 6px;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    .editor-wrapper:hover .editor-actions {
        opacity: 1;
        pointer-events: auto;
    }

    .editor-actions .q-btn {
        min-width: 28px;
        width: 26px;
        height: 26px;
        padding: 0;
        background: rgba(60, 63, 65, 0.92);
        border: 1px solid var(--jb-border);
        color: var(--jb-muted);
        border-radius: 4px;
    }

    .editor-actions .q-btn:hover {
        background: #4b4f52;
        color: var(--jb-text);
    }

    .sql-editor {
        height: 70vh;
    }

    .sql-editor .cm-editor {
        height: 100%;
        background: var(--jb-editor) !important;
        border-radius: 0 0 8px 8px;
    }

    .sql-editor .cm-gutters {
        background: var(--jb-editor) !important;
        border-right: 1px solid var(--jb-border-soft) !important;
    }

    .sql-editor .cm-activeLine,
    .sql-editor .cm-activeLineGutter {
        background: rgba(75, 79, 82, 0.28) !important;
    }

    .sql-editor .cm-scroller {
        overflow: auto;
    }

    .output-section {
        width: 100%;
        max-width: 980px;
        background: transparent;
        border: none;
        box-shadow: none;
        margin-top: 8px;
    }

    .file-tree {
        background: var(--jb-panel);
        border: 1px solid var(--jb-border-soft);
        border-radius: 8px;
        padding: 12px 18px 12px 14px;
    }

    .jb-input .q-field__control,
    .dark-input .q-field__control,
    .tree-input .q-field__control {
        min-height: 32px;
        height: 32px;
        background: var(--jb-input);
        color: var(--jb-text);
        border-radius: 4px;
        box-shadow: inset 0 -1px 0 var(--jb-border);
    }

    .jb-input .q-field__control:hover,
    .dark-input .q-field__control:hover,
    .tree-input .q-field__control:hover {
        background: var(--jb-input-hover);
    }

    .jb-input input,
    .dark-input input,
    .tree-input input,
    .jb-input .q-field__native,
    .dark-input .q-field__native,
    .tree-input .q-field__native {
        color: var(--jb-text);
        font-size: 13px;
        padding-left: 12px !important;
        padding-right: 12px !important;
    }

    .field-label,
    .dark-input .q-field__label,
    .tree-input .q-field__label {
        color: var(--jb-muted);
        font-size: 12px;
    }

    .jb-input input::placeholder,
    .dark-input input::placeholder,
    .tree-input input::placeholder {
        color: var(--jb-muted-2);
    }

    .tree-input,
    .path-text,
    .log-area textarea {
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }

    .tree-input .q-field__native,
    .tree-input .q-field__input {
        min-height: 32px;
        padding-top: 0;
        padding-bottom: 0;
    }

    .tree-row {
        min-height: 34px;
        padding-right: 12px;
    }

    .tree-input {
        width: calc(100% - 12px);
    }

    .tree-file-row {
        border-left: 1px solid var(--jb-border-soft);
        margin-left: 12px;
    }

    .action-button {
        min-height: 31px;
        height: 31px;
        border-radius: 4px;
        text-transform: none;
        font-weight: 500;
        background: #3c3f41;
        border: 1px solid #55585c;
        color: var(--jb-text);
    }

    .primary-action {
        background: #365880;
        border-color: var(--jb-accent);
        color: #ffffff;
    }

    .secondary-action {
        background: #3c3f41;
        border-color: #55585c;
        color: var(--jb-text);
    }

    .action-button:hover,
    .secondary-action:hover {
        background: #4b4f52;
    }

    .primary-action:hover {
        background: #416996;
        border-color: var(--jb-accent-hover);
    }

    .status-chip {
        max-width: 240px;
        min-height: 28px;
        padding: 4px 10px;
        border: 1px solid var(--jb-border-soft);
        border-radius: 4px;
        color: var(--jb-muted);
        background: var(--jb-panel);
        font-size: 12px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .status-warning,
    .status-error {
        background: #3b1f24;
        border-color: #7f3b45;
        color: #ffb4bf;
    }

    .section-title {
        color: var(--jb-text);
        letter-spacing: 0;
    }

    .muted-text {
        color: var(--jb-muted);
    }

    .log-area .q-field__control {
        background: var(--jb-panel);
        border: 1px solid var(--jb-border-soft);
        border-radius: 8px;
    }

    .log-area textarea {
        color: var(--jb-text);
        font-size: 12px;
        line-height: 1.45;
        padding: 10px 12px;
    }
    """
)

with ui.column().classes("w-full min-h-screen p-6 gap-5"):
    ui.label("SQL Migrator").classes("app-title text-2xl font-bold")

    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        with ui.column().classes("w-1/2 editor-panel").style("min-width: 0;"):
            with ui.row().classes("editor-titlebar w-full items-center justify-between no-wrap"):
                ui.label("Oracle SQL").classes("font-semibold")
            with ui.element("div").classes("editor-wrapper"):
                oracle_editor = ui.codemirror(
                    value=state.oracle_sql,
                    language="sql",
                    theme="vscodeDark",
                    line_wrapping=True,
                    on_change=update_oracle_sql,
                ).classes("w-full sql-editor")
                with ui.element("div").classes("editor-actions"):
                    ui.button(icon="content_copy", on_click=copy_oracle_sql).props("flat dense")
                    ui.button(icon="format_align_left", on_click=format_oracle_sql).props("flat dense")

        with ui.column().classes("w-1/2 editor-panel").style("min-width: 0;"):
            with ui.row().classes("editor-titlebar w-full items-center justify-between no-wrap"):
                ui.label("StarRocks / dbt SQL").classes("font-semibold")
            with ui.element("div").classes("editor-wrapper"):
                starrocks_editor = ui.codemirror(
                    value=state.starrocks_sql,
                    language="sql",
                    theme="vscodeDark",
                    line_wrapping=True,
                    on_change=update_starrocks_sql,
                ).classes("w-full sql-editor")
                with ui.element("div").classes("editor-actions"):
                    ui.button(icon="content_copy", on_click=copy_starrocks_sql).props("flat dense")
                    ui.button(icon="format_align_left", on_click=format_starrocks_sql).props("flat dense")

    with ui.row().classes("w-full gap-2 items-center"):
        ui.button("Convert", on_click=convert_sql).props("flat no-caps dense").classes("action-button primary-action px-5")
        ui.button("Clear", on_click=clear_all).props("flat no-caps dense").classes("action-button secondary-action px-4")
        ui.button("dbt parse", on_click=dbt_parse).props("flat no-caps dense").classes("action-button secondary-action px-4")
        ui.button("Save", on_click=save_files).props("flat no-caps dense").classes("action-button secondary-action px-4")
        ui.button("Save + dbt run", on_click=save_and_dbt_run).props("flat no-caps dense").classes("action-button secondary-action px-4")
        status_label = ui.label(DEFAULT_STATUS).classes("status-chip")

    with ui.column().classes("w-full max-w-5xl gap-3 output-section"):
        ui.label("Output structure").classes("section-title text-lg font-semibold")

        ui.label("Base path").classes("field-label")
        base_path_input = ui.input(
            value=state.base_path,
            on_change=update_base_path,
        ).props("dense borderless").classes("w-full jb-input")

        with ui.column().classes("w-full gap-2 file-tree"):
            with ui.row().classes("tree-row w-full items-center gap-2 no-wrap"):
                ui.icon("folder").style("color: #c9a26d;").classes("text-lg")
                folder_input = ui.input(
                    value=state.folder_name,
                    placeholder="folder_name",
                    on_change=update_folder_name,
                ).props("dense borderless").classes("tree-input folder-input w-full")

            with ui.row().classes("tree-row w-full items-center gap-2 pl-8 no-wrap tree-file-row"):
                ui.icon("code").style("color: #78a8c7;").classes("text-lg")
                sql_file_input = ui.input(
                    value=state.sql_file_name,
                    placeholder="MODEL.sql",
                    on_change=update_sql_file_name,
                ).props("dense borderless").classes("tree-input file-input w-full")

            with ui.row().classes("tree-row w-full items-center gap-2 pl-8 no-wrap tree-file-row"):
                ui.icon("data_object").style("color: #7aa887;").classes("text-lg")
                yaml_file_input = ui.input(
                    value=state.yaml_file_name,
                    placeholder="_MODEL_MODELS.yml",
                    on_change=update_yaml_file_name,
                ).props("dense borderless").classes("tree-input file-input w-full")

        ui.label("Will save").classes("text-xs muted-text")
        sql_path_label = ui.label("").classes("path-text text-xs muted-text")
        yaml_path_label = ui.label("").classes("path-text text-xs muted-text")

    with ui.row().classes("w-full gap-4 no-wrap"):
        with ui.column().classes("w-1/2 gap-2"):
            ui.label("Warnings").classes("section-title font-semibold")
            warnings_area = ui.textarea(value="No warnings").classes("w-full log-area").props("readonly autogrow")
        with ui.column().classes("w-1/2 gap-2"):
            ui.label("Logs").classes("section-title font-semibold")
            logs_area = ui.textarea(value="No logs").classes("w-full log-area").props("readonly autogrow")


refresh_output_paths()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="SQL Migrator")
