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


def test_question_and_analysis_mappers_configure_from_model_registry():
    api_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.models import Analysis, Question\n"
            "from sqlalchemy.orm import configure_mappers\n"
            "configure_mappers()",
        ],
        cwd=api_root,
        env={**os.environ, "PYTHONPATH": str(api_root)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_question_and_analysis_schemas_import_in_any_order():
    api_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.schemas.analysis import AnalysisInput, AnalysisResult\n"
            "from app.schemas.question import QuestionRead\n"
            "AnalysisInput.model_json_schema()\n"
            "AnalysisResult.model_json_schema()\n"
            "QuestionRead.model_json_schema()",
        ],
        cwd=api_root,
        env={**os.environ, "PYTHONPATH": str(api_root)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
