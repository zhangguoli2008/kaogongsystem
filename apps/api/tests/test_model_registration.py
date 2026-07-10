import os
import subprocess
import sys
from pathlib import Path


def test_user_mapper_configures_without_auth_import_order():
    api_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.models.user import User\n"
            "from sqlalchemy.orm import configure_mappers\n"
            "configure_mappers()",
        ],
        cwd=api_root,
        env={**os.environ, "PYTHONPATH": str(api_root)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
