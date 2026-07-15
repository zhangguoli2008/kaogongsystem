#!/usr/bin/env python3
"""Atomically consume the local one-shot allowance for a paid OCR smoke."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("one-shot marker write was incomplete")
        remaining = remaining[written:]


def consume(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("one-shot guard path must be absolute")
    if path.name != "paid-ocr.spent":
        raise ValueError("one-shot guard must use the fixed paid-ocr.spent name")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(path.parent, directory_flags)
    try:
        parent_status = os.fstat(directory)
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or parent_status.st_uid != os.geteuid()
            or stat.S_IMODE(parent_status.st_mode) != 0o700
        ):
            raise PermissionError(
                "one-shot guard parent must be an owned mode-0700 directory"
            )

        marker_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        marker_flags |= getattr(os, "O_NOFOLLOW", 0)
        marker = os.open(path.name, marker_flags, 0o600, dir_fd=directory)
        try:
            marker_status = os.fstat(marker)
            if (
                not stat.S_ISREG(marker_status.st_mode)
                or marker_status.st_uid != os.geteuid()
                or marker_status.st_nlink != 1
                or stat.S_IMODE(marker_status.st_mode) != 0o600
            ):
                raise PermissionError("one-shot marker has unsafe ownership or mode")
            _write_all(marker, b"spent\n")
            os.fsync(marker)
        finally:
            os.close(marker)
        os.fsync(directory)
    finally:
        os.close(directory)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: consume-ocr-one-shot-guard.py ABSOLUTE_PATH", file=sys.stderr)
        return 2
    try:
        consume(Path(argv[1]))
    except (FileExistsError, OSError, ValueError) as error:
        print(f"one-shot guard refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
