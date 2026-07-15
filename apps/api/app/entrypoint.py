import os
from pathlib import Path

import uvicorn

from app.core.config import get_settings


APP_UID = 10001
APP_GID = 10001


def resolve_port(raw_port: str | None) -> int:
    try:
        port = int("8000" if raw_port is None else raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return port


def prepare_runtime(upload_dir: Path, uid: int = APP_UID, gid: int = APP_GID) -> None:
    euid = os.geteuid()
    if euid != 0 and (euid != uid or os.getegid() != gid or os.getgroups()):
        raise RuntimeError("UPLOAD_DIR runtime identity is invalid")
    upload_dir.mkdir(parents=True, exist_ok=True)
    if euid == 0:
        os.chown(upload_dir, uid, gid)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if not os.access(upload_dir, os.W_OK | os.X_OK):
        raise RuntimeError("UPLOAD_DIR is not writable by the application user")


def main() -> None:
    settings = get_settings()
    settings.validate_for_startup()
    port = resolve_port(os.environ.get("PORT"))
    prepare_runtime(settings.upload_dir)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
