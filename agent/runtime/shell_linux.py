from __future__ import annotations


def build_linux_shell_command(shell_path: str, command: str) -> list[str]:
    return [shell_path, "-lc", command]
