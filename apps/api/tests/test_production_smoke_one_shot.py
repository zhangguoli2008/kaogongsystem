from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "production-smoke.sh"


def _run_real_smoke(
    tmp_path: Path,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    image = tmp_path / "question.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "WEB_URL": "https://web-guard-test.railway.app",
        "API_URL": "https://api-guard-test.railway.app",
        "EXPECTED_OCR_PROVIDER": "tencent_question_split",
        "SMOKE_IMAGE_PATH": str(image),
        "SMOKE_IMAGE_SHA256": hashlib.sha256(image.read_bytes()).hexdigest(),
        **overrides,
    }
    return subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_real_smoke_requires_external_one_shot_guard_before_network(
    tmp_path: Path,
) -> None:
    result = _run_real_smoke(tmp_path, SMOKE_EMAIL="rollout@example.com")

    assert result.returncode != 0
    assert "SMOKE_OCR_ONE_SHOT_GUARD_FILE is required" in result.stderr


def test_real_smoke_requires_fixed_email_before_network(tmp_path: Path) -> None:
    result = _run_real_smoke(
        tmp_path,
        SMOKE_OCR_ONE_SHOT_GUARD_FILE=str(tmp_path / "paid-ocr.spent"),
    )

    assert result.returncode != 0
    assert "SMOKE_EMAIL is required" in result.stderr


def test_real_smoke_requires_approved_image_digest_before_network(
    tmp_path: Path,
) -> None:
    result = _run_real_smoke(
        tmp_path,
        SMOKE_EMAIL="rollout@example.com",
        SMOKE_OCR_ONE_SHOT_GUARD_FILE=str(tmp_path / "paid-ocr.spent"),
        SMOKE_IMAGE_SHA256="",
    )

    assert result.returncode != 0
    assert "SMOKE_IMAGE_SHA256 is required" in result.stderr


def test_real_smoke_rejects_unapproved_image_bytes_before_network(
    tmp_path: Path,
) -> None:
    result = _run_real_smoke(
        tmp_path,
        SMOKE_EMAIL="rollout@example.com",
        SMOKE_OCR_ONE_SHOT_GUARD_FILE=str(tmp_path / "paid-ocr.spent"),
        SMOKE_IMAGE_SHA256="0" * 64,
    )

    assert result.returncode != 0
    assert "SMOKE_IMAGE_SHA256 mismatch" in result.stderr


def test_smoke_disables_curl_configuration_and_retries() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "curl_common=(\n  --disable\n  --retry 0\n" in source


def test_server_download_digest_code_runs_without_hashlib_file_digest(
    tmp_path: Path,
) -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    prefix = """downloaded_image_sha=$(python3 - "$tmp_dir/uploaded-image" <<'PY'
"""
    digest_code = source.split(prefix, maxsplit=1)[1].split("\nPY\n", maxsplit=1)[0]
    downloaded = tmp_path / "downloaded-image"
    downloaded.write_bytes(b"server-returned-approved-image")

    assert "file_digest" not in digest_code
    interpreters = {sys.executable}
    system_python = Path("/usr/bin/python3")
    if system_python.exists():
        interpreters.add(str(system_python))
    expected = hashlib.sha256(downloaded.read_bytes()).hexdigest()
    for interpreter in interpreters:
        result = subprocess.run(
            [interpreter, "-", str(downloaded)],
            input=digest_code,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected


def test_real_guard_is_consumed_immediately_before_the_only_ocr_post() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    expected = """if [[ "$expected_ocr_provider" == "tencent_question_split" ]]; then
  python3 "$script_dir/consume-ocr-one-shot-guard.py" \\
    "$SMOKE_OCR_ONE_SHOT_GUARD_FILE" \\
    || die "real OCR one-shot guard is unsafe or already consumed"
fi
http_request 200 "$tmp_dir/ocr.json" "$tmp_dir/ocr.headers" \\
"""

    assert expected in source
    assert source.count('"$api_proxy/ocr"') == 1
