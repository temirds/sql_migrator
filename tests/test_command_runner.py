from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import command_runner
from command_runner import CommandResult, run_command_in_thread, run_command_sync


def test_python_version_command_returns_zero() -> None:
    result = run_command_sync(f'"{sys.executable}" --version', Path.cwd())

    assert result.return_code == 0
    assert "Python" in (result.stdout + result.stderr)
    assert result.error is None


def test_missing_command_does_not_raise() -> None:
    result = run_command_sync("definitely_missing_command_for_sql_migrator_tests", Path.cwd())

    assert result.return_code != 0 or result.error is not None


def test_async_runner_uses_to_thread(monkeypatch) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        return CommandResult(
            command_text=str(args[0]),
            cwd=str(args[1]),
            return_code=0,
            stdout="ok",
            stderr="",
            error=None,
        )

    monkeypatch.setattr(command_runner.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(run_command_in_thread("echo ok", Path.cwd()))

    assert result.return_code == 0
    assert calls == [(command_runner.run_command_sync, ("echo ok", Path.cwd()))]
