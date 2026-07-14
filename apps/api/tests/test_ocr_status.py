import pytest


def register(client, email: str = "ocr-status@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text


def expected_status(*, provider: str, configured: bool) -> dict[str, object]:
    return {
        "provider": provider,
        "configured": configured,
        "api_name": "QuestionSplitOCR",
        "supports_multi_question": True,
        "supports_pdf": True,
        "supports_options": True,
        "use_new_model": False,
    }


def test_ocr_status_requires_authentication(client) -> None:
    response = client.get("/api/v1/ocr/status")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_session"


def test_mock_ocr_status_is_always_configured(client) -> None:
    register(client)

    response = client.get("/api/v1/ocr/status")

    assert response.status_code == 200
    assert response.json() == expected_status(provider="mock", configured=True)


@pytest.mark.parametrize(
    ("secret_id", "secret_key"),
    [
        (None, None),
        ("test-secret-id", None),
        (None, "test-secret-key"),
        ("", "test-secret-key"),
        ("test-secret-id", ""),
    ],
)
def test_tencent_ocr_status_is_unconfigured_without_both_credentials(
    client, secret_id: str | None, secret_key: str | None
) -> None:
    register(client)
    client.app.state.settings.ocr_provider = "tencent_question_split"
    client.app.state.settings.tencentcloud_secret_id = secret_id
    client.app.state.settings.tencentcloud_secret_key = secret_key

    response = client.get("/api/v1/ocr/status")

    assert response.status_code == 200
    assert response.json() == expected_status(
        provider="tencent_question_split", configured=False
    )


def test_tencent_ocr_status_is_configured_with_both_credentials(client) -> None:
    register(client)
    client.app.state.settings.ocr_provider = "tencent_question_split"
    client.app.state.settings.tencentcloud_secret_id = "test-secret-id"
    client.app.state.settings.tencentcloud_secret_key = "test-secret-key"

    response = client.get("/api/v1/ocr/status")

    assert response.status_code == 200
    assert response.json() == expected_status(
        provider="tencent_question_split", configured=True
    )


def test_client_cannot_override_server_controlled_ocr_status(client) -> None:
    register(client)

    response = client.get(
        "/api/v1/ocr/status",
        params={
            "provider": "tencent_question_split",
            "api_name": "GeneralAccurateOCR",
            "supports_pdf": "false",
            "use_new_model": "true",
        },
    )

    assert response.status_code == 200
    assert response.json() == expected_status(provider="mock", configured=True)
