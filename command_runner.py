from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback


@dataclass
class CommandResult:
    command_text: str
    cwd: str
    return_code: int | None
    stdout: str
    stderr: str
    error: str | None = None


def run_command_sync(command_text: str, cwd: Path) -> CommandResult:
    try:
        completed = subprocess.run(
            command_text,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            command_text=command_text,
            cwd=str(cwd),
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error=None,
        )
    except Exception as exc:
        return CommandResult(
            command_text=command_text,
            cwd=str(cwd),
            return_code=None,
            stdout="",
            stderr="",
            error=(
                f"{type(exc).__name__}: {exc}\n"
                f"repr: {repr(exc)}\n"
                f"traceback:\n{traceback.format_exc()}"
            ),
        )


async def run_command_in_thread(command_text: str, cwd: Path) -> CommandResult:
    return await asyncio.to_thread(run_command_sync, command_text, cwd)


def format_command_start_log(command_text: str, cwd: Path) -> str:
    return "\n".join(
        [
            f"project_dir: {cwd}",
            f"cwd: {cwd}",
            f"command text: {command_text}",
            f"python executable: {sys.executable}",
            f"platform: {platform.platform()}",
            f"PATH: {os.environ.get('PATH', '')}",
            "started",
        ]
    )


def format_command_log(result: CommandResult) -> str:
    return "\n".join(
        [
            f"project_dir: {result.cwd}",
            f"cwd: {result.cwd}",
            f"command text: {result.command_text}",
            f"python executable: {sys.executable}",
            f"platform: {platform.platform()}",
            f"PATH: {os.environ.get('PATH', '')}",
            f"return code: {result.return_code}",
            "stdout:",
            result.stdout.strip(),
            "stderr:",
            result.stderr.strip(),
            "error:",
            (result.error or "").strip(),
        ]
    )
