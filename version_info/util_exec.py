from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int


def run_argv(argv: list[str], *, timeout_s: float = 10.0) -> ExecResult:
    """Run a subprocess without invoking a shell.

    - argv-only (no string interpolation)
    - captures stdout/stderr
    - deterministic timeouts
    """

    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=os.environ.copy(),
        )
        return ExecResult(
            ok=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        err = e.stderr
        return ExecResult(
            ok=False,
            stdout=out.decode() if isinstance(out, bytes) else (out or ""),
            stderr=err.decode() if isinstance(err, bytes) else (err or ""),
            exit_code=124,
        )
    except Exception as e:
        return ExecResult(ok=False, stdout="", stderr=str(e), exit_code=1)
