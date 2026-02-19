from __future__ import annotations

import subprocess
from typing import Any

from agent.runtime.executor import CommandExecutor


def test_executor_converts_timeout_to_failed_execution(monkeypatch: Any) -> None:
    def _raise_timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs.get("timeout", 0),
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    executor = CommandExecutor(
        linux_shell="/bin/bash",
        windows_shell="pwsh",
        timeout_seconds=12,
    )
    result = executor.run("sleep 30")

    assert result.command == "sleep 30"
    assert result.exit_code == 124
    assert result.stdout == "partial stdout"
    assert "partial stderr" in result.stderr
    assert "timed out after 12 seconds" in result.stderr


def test_executor_converts_subprocess_errors_to_failed_execution(monkeypatch: Any) -> None:
    def _raise_os_error(*args: Any, **kwargs: Any) -> Any:
        raise OSError("shell not found")

    monkeypatch.setattr(subprocess, "run", _raise_os_error)

    executor = CommandExecutor(
        linux_shell="/bin/bash",
        windows_shell="pwsh",
        timeout_seconds=12,
    )
    result = executor.run("echo hello")

    assert result.command == "echo hello"
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Command execution failed (OSError): shell not found"
