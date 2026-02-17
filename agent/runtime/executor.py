from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from agent.runtime.shell_linux import build_linux_shell_command
from agent.runtime.shell_windows import build_windows_shell_command


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
