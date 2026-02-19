from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from agent.runtime.shell_linux import build_linux_shell_command
from agent.runtime.shell_windows import build_windows_shell_command


def _coerce_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@dataclass
class CommandExecution:
    command: str
    exit_code: int
    stdout: str
    stderr: str


class CommandExecutor:
    def __init__(self, linux_shell: str, windows_shell: str, timeout_seconds: int) -> None:
        self.linux_shell = linux_shell
        self.windows_shell = windows_shell
        self.timeout_seconds = timeout_seconds

    def _build_command(self, command: str) -> list[str]:
        if platform.system().lower().startswith("win"):
            return build_windows_shell_command(self.windows_shell, command)
        return build_linux_shell_command(self.linux_shell, command)

    def run(self, command: str) -> CommandExecution:
        try:
            argv = self._build_command(command)
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return CommandExecution(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_subprocess_output(exc.stdout)
            stderr = _coerce_subprocess_output(exc.stderr)
            timeout_note = f"Command timed out after {self.timeout_seconds} seconds"
            stderr_text = f"{stderr.rstrip()}\n{timeout_note}" if stderr.strip() else timeout_note
            return CommandExecution(
                command=command,
                exit_code=124,
                stdout=stdout,
                stderr=stderr_text,
            )
        except Exception as exc:
            return CommandExecution(
                command=command,
                exit_code=1,
                stdout="",
                stderr=f"Command execution failed ({exc.__class__.__name__}): {exc}",
            )
