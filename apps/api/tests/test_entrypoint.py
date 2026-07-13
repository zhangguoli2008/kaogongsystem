import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import entrypoint


API_ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, 8000), ("8000", 8000), ("49152", 49152)]
)
def test_resolve_port(raw: str | None, expected: int) -> None:
    assert entrypoint.resolve_port(raw) == expected


@pytest.mark.parametrize("raw", ["", "0", "65536", "not-a-port"])
def test_resolve_port_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="PORT"):
        entrypoint.resolve_port(raw)


def test_prepare_runtime_chowns_volume_then_drops_root_privileges(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        entrypoint.os,
        "chown",
        lambda path, uid, gid: calls.append(("chown", path, uid, gid)),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "setgroups",
        lambda groups: calls.append(("setgroups", groups)),
    )
    monkeypatch.setattr(
        entrypoint.os, "setgid", lambda gid: calls.append(("setgid", gid))
    )
    monkeypatch.setattr(
        entrypoint.os, "setuid", lambda uid: calls.append(("setuid", uid))
    )
    monkeypatch.setattr(
        entrypoint.os,
        "access",
        lambda path, mode: calls.append(("access", path, mode)) or True,
    )

    entrypoint.prepare_runtime(upload_dir)

    assert upload_dir.is_dir()
    assert calls == [
        ("chown", upload_dir, 10001, 10001),
        ("setgroups", []),
        ("setgid", 10001),
        ("setuid", 10001),
        ("access", upload_dir, entrypoint.os.W_OK | entrypoint.os.X_OK),
    ]


def test_prepare_runtime_accepts_exact_application_identity_without_change(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(entrypoint.os, "getegid", lambda: 10001)
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: [])
    monkeypatch.setattr(
        entrypoint.os,
        "chown",
        lambda *args: pytest.fail("non-root startup must not chown"),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "setgroups",
        lambda *args: pytest.fail("non-root startup must not set groups"),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "setgid",
        lambda *args: pytest.fail("non-root startup must not set gid"),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "setuid",
        lambda *args: pytest.fail("non-root startup must not set uid"),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "access",
        lambda path, mode: True,
    )

    entrypoint.prepare_runtime(upload_dir)

    assert upload_dir.is_dir()


@pytest.mark.parametrize(
    ("euid", "egid", "groups"),
    [
        (10002, 10001, []),
        (10001, 10002, []),
        (10001, 10001, [10001]),
    ],
)
def test_prepare_runtime_rejects_unexpected_non_root_identity_before_filesystem(
    monkeypatch,
    tmp_path: Path,
    euid: int,
    egid: int,
    groups: list[int],
) -> None:
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: euid)
    monkeypatch.setattr(entrypoint.os, "getegid", lambda: egid)
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: groups)
    monkeypatch.setattr(
        entrypoint.os,
        "access",
        lambda path, mode: pytest.fail(
            "identity rejection must precede filesystem access"
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        entrypoint.prepare_runtime(upload_dir)

    assert str(exc_info.value) == "UPLOAD_DIR runtime identity is invalid"
    assert not upload_dir.exists()


def test_prepare_runtime_fails_when_upload_directory_is_not_writable(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    checked: list[tuple[Path, int]] = []
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(entrypoint.os, "getegid", lambda: 10001)
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: [])
    monkeypatch.setattr(
        entrypoint.os,
        "access",
        lambda path, mode: checked.append((path, mode)) or False,
    )

    with pytest.raises(RuntimeError) as exc_info:
        entrypoint.prepare_runtime(upload_dir)

    assert str(exc_info.value) == "UPLOAD_DIR is not writable by the application user"
    assert str(upload_dir) not in str(exc_info.value)
    assert checked == [(upload_dir, entrypoint.os.W_OK | entrypoint.os.X_OK)]


def test_main_validates_then_prepares_runtime_before_starting_uvicorn(
    monkeypatch, tmp_path: Path
) -> None:
    upload_dir = tmp_path / "uploads"
    calls: list[tuple[object, ...]] = []
    settings = SimpleNamespace(
        upload_dir=upload_dir,
        validate_for_startup=lambda: calls.append(("validate",)),
    )
    monkeypatch.setenv("PORT", "49152")
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(
        entrypoint,
        "resolve_port",
        lambda raw: calls.append(("resolve_port", raw)) or 49152,
    )
    monkeypatch.setattr(
        entrypoint,
        "prepare_runtime",
        lambda path: calls.append(("prepare_runtime", path)),
    )
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        lambda app, **kwargs: calls.append(("uvicorn.run", app, kwargs)),
    )

    entrypoint.main()

    assert calls == [
        ("validate",),
        ("resolve_port", "49152"),
        ("prepare_runtime", upload_dir),
        (
            "uvicorn.run",
            "app.main:app",
            {"host": "0.0.0.0", "port": 49152},
        ),
    ]


def test_main_fails_closed_before_runtime_preparation(monkeypatch) -> None:
    def reject_configuration() -> None:
        raise ValueError("invalid production configuration")

    settings = SimpleNamespace(
        upload_dir=Path("/data/uploads"),
        validate_for_startup=reject_configuration,
    )
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(
        entrypoint,
        "prepare_runtime",
        lambda path: pytest.fail("runtime must not be prepared for invalid config"),
    )
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("server must not start for invalid config"),
    )

    with pytest.raises(ValueError, match="invalid production configuration"):
        entrypoint.main()


def test_main_rejects_invalid_port_before_runtime_preparation(monkeypatch) -> None:
    settings = SimpleNamespace(
        upload_dir=Path("/data/uploads"),
        validate_for_startup=lambda: None,
    )
    monkeypatch.setenv("PORT", "not-a-port")
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(
        entrypoint,
        "prepare_runtime",
        lambda path: pytest.fail("runtime must not be prepared for an invalid port"),
    )
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("server must not start for invalid port"),
    )

    with pytest.raises(ValueError, match="PORT"):
        entrypoint.main()


def test_dockerfile_leaves_identity_drop_to_entrypoint() -> None:
    instructions = [
        line.strip()
        for line in (API_ROOT / "Dockerfile").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert all(
        instruction.split(maxsplit=1)[0].upper() != "USER"
        for instruction in instructions
    )


def test_dockerfile_keeps_application_code_root_owned() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text().replace("\\\n", " ")
    chown_commands = [
        line.strip() for line in dockerfile.splitlines() if "chown" in line
    ]

    assert chown_commands
    assert all("/app" not in command for command in chown_commands)
    assert any("/data/uploads" in command for command in chown_commands)


def test_dockerfile_default_command_uses_entrypoint() -> None:
    instructions = [
        line.strip()
        for line in (API_ROOT / "Dockerfile").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert instructions[-1] == 'CMD ["python", "-m", "app.entrypoint"]'


def test_railway_manifest_pins_entrypoint_start_command() -> None:
    manifest = json.loads((API_ROOT / "railway.json").read_text())

    assert manifest["deploy"]["startCommand"] == "python -m app.entrypoint"


def test_dockerignore_excludes_local_secrets_and_test_artifacts() -> None:
    patterns = set((API_ROOT / ".dockerignore").read_text().splitlines())

    assert {
        ".env",
        ".env.*",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "*.py[cod]",
        "*.db",
        "tests",
        "!.env.example",
    } <= patterns


def test_dockerignore_excludes_nested_secrets_and_test_artifacts() -> None:
    patterns = set((API_ROOT / ".dockerignore").read_text().splitlines())

    assert {
        "**/.env",
        "**/.env.*",
        "**/.pytest_cache/",
        "**/.venv/",
        "**/__pycache__/",
        "**/*.py[cod]",
        "**/*.db",
        "**/tests/",
    } <= patterns
