from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ROLLOUT_PLAN = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-15-railway-live-tencent-ocr-safety-correction.md"
)


def test_rollout_discovers_pinned_cli_deployments_by_cli_message() -> None:
    source = ROLLOUT_PLAN.read_text(encoding="utf-8")

    assert ".meta.cliMessage == $message" in source
    assert ".meta.deploymentMessage" not in source


def test_deploy_snapshot_is_read_only_and_runtime_user_readable() -> None:
    source = ROLLOUT_PLAN.read_text(encoding="utf-8")

    assert 'find "$DEPLOY_SOURCE_DIR" -type f -exec chmod 444 {} +' in source
    assert 'find "$DEPLOY_SOURCE_DIR" -type d -exec chmod 555 {} +' in source
    assert 'find "$DEPLOY_SOURCE_DIR" -type f -exec chmod 400 {} +' not in source
    assert 'find "$DEPLOY_SOURCE_DIR" -type d -exec chmod 500 {} +' not in source


def test_detached_upload_omits_json_and_ci_modes() -> None:
    source = ROLLOUT_PLAN.read_text(encoding="utf-8")
    upload_stanza = source.split(
        'if "${railway_cli[@]}" up',
        maxsplit=1,
    )[1].split('>"$upload_log"; then', maxsplit=1)[0]

    assert "--yes --detach --message" in upload_stanza
    assert "--json" not in upload_stanza
    assert "--ci" not in upload_stanza
