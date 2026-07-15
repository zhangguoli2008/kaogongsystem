from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GUARD_HELPER = REPOSITORY_ROOT / "scripts" / "consume-ocr-one-shot-guard.py"


def _consume_guard(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD_HELPER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_guard_can_be_consumed_exactly_once(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    guard = tmp_path / "paid-ocr.spent"

    first = _consume_guard(guard)

    assert first.returncode == 0, first.stderr
    assert guard.read_text(encoding="utf-8") == "spent\n"
    assert stat.S_IMODE(guard.stat().st_mode) == 0o600

    second = _consume_guard(guard)

    assert second.returncode != 0
    assert guard.read_text(encoding="utf-8") == "spent\n"


def test_guard_rejects_any_marker_name_other_than_paid_ocr_spent(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)

    result = _consume_guard(tmp_path / "replaceable-marker")

    assert result.returncode != 0
    assert not (tmp_path / "replaceable-marker").exists()


def test_concurrent_consumers_allow_exactly_one_success(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    guard = tmp_path / "paid-ocr.spent"
    processes = [
        subprocess.Popen(
            [sys.executable, str(GUARD_HELPER), str(guard)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]

    results = [process.communicate() + (process.returncode,) for process in processes]

    assert sum(returncode == 0 for _stdout, _stderr, returncode in results) == 1
    assert guard.read_text(encoding="utf-8") == "spent\n"


def test_guard_rejects_non_private_parent_directory(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)

    result = _consume_guard(tmp_path / "paid-ocr.spent")

    assert result.returncode != 0
    assert not (tmp_path / "paid-ocr.spent").exists()


def test_guard_rejects_symlinked_parent_directory(tmp_path: Path) -> None:
    secure_parent = tmp_path / "secure"
    secure_parent.mkdir(mode=0o700)
    symlinked_parent = tmp_path / "alias"
    symlinked_parent.symlink_to(secure_parent, target_is_directory=True)

    result = _consume_guard(symlinked_parent / "paid-ocr.spent")

    assert result.returncode != 0
    assert not (secure_parent / "paid-ocr.spent").exists()
