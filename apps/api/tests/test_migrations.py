import os
import sqlite3
import subprocess
import sys
from pathlib import Path


API_ROOT = Path(__file__).parents[1]


def run_alembic(database_path: Path, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=API_ROOT,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
            "PYTHONPATH": str(API_ROOT),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def schema(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in rows}


def columns(database_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in rows}


def version(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_wrong_question_migration_supports_fresh_existing_and_downgrade(tmp_path):
    fresh = tmp_path / "fresh.db"
    run_alembic(fresh, "upgrade", "head")
    run_alembic(fresh, "check")
    assert version(fresh) == "0006_question_split_ocr"
    assert {
        "users",
        "user_settings",
        "questions",
        "analyses",
        "uploaded_assets",
        "review_records",
        "ocr_tasks",
    } <= schema(fresh)
    assert "analysis_error_code" in columns(fresh, "questions")
    assert {
        "id",
        "user_id",
        "source_file_id",
        "provider",
        "api_name",
        "source_file_hash",
        "pdf_page_number",
        "parameter_version",
        "idempotency_key",
        "status",
        "question_count",
        "provider_request_id",
        "normalized_result_json",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
    } == columns(fresh, "ocr_tasks")

    existing = tmp_path / "existing.db"
    run_alembic(existing, "upgrade", "0003_uploaded_assets")
    assert version(existing) == "0003_uploaded_assets"
    assert "analysis_error_code" not in columns(existing, "questions")

    run_alembic(existing, "upgrade", "0005_review_records")
    assert version(existing) == "0005_review_records"
    assert "ocr_tasks" not in schema(existing)

    run_alembic(existing, "upgrade", "head")
    run_alembic(existing, "check")
    assert version(existing) == "0006_question_split_ocr"
    assert {
        "questions",
        "analyses",
        "uploaded_assets",
        "review_records",
        "ocr_tasks",
    } <= schema(existing)
    assert "analysis_error_code" in columns(existing, "questions")
    assert {"result_status", "review_note", "reviewed_at"} <= columns(
        existing, "review_records"
    )

    run_alembic(existing, "downgrade", "0005_review_records")
    assert version(existing) == "0005_review_records"
    assert "ocr_tasks" not in schema(existing)
    run_alembic(existing, "downgrade", "0004_analysis_error_code")
    assert version(existing) == "0004_analysis_error_code"
    assert "review_records" not in schema(existing)
    run_alembic(existing, "downgrade", "0003_uploaded_assets")
    assert version(existing) == "0003_uploaded_assets"
    assert "analysis_error_code" not in columns(existing, "questions")
