from io import BytesIO
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import UploadFile
from PIL import Image, ImageDraw, ImageFilter
import pytest
from pypdf import PdfWriter
from pypdf.errors import LimitReachedError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base
from app.models.upload import UploadedAsset
from app.api.routes.uploads import upload_question_image as upload_question_image_route
from app.core.rate_limit import DualWindowRateLimiter
from app.services import storage
from app.services.storage import (
    InvalidFilename,
    InvalidImage,
    inspect_image,
    save_image,
)


def register(client, email: str):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text
    return dict(response.cookies)


def png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def image_bytes(image_format: str, *, size: tuple[int, int] = (640, 800)) -> bytes:
    image = clear_question_image(size)
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def clear_question_image(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("L", size, 205)
    draw = ImageDraw.Draw(image)
    margin = max(20, width // 12)
    line_height = max(5, height // 100)
    line_gap = max(24, height // 16)
    for index, y in enumerate(range(line_gap, height - line_gap, line_gap)):
        right = width - margin - (index % 3) * max(12, width // 14)
        draw.rectangle((margin, y, right, y + line_height), fill=35)
    return image.convert("RGB")


def quality_image_bytes(quality: str, *, size: tuple[int, int] = (600, 800)) -> bytes:
    if quality == "dark":
        image = Image.new("L", size, 15)
    elif quality == "bright":
        image = Image.new("L", size, 252)
    else:
        image = clear_question_image(size)
        if quality == "blurry":
            image = image.filter(ImageFilter.GaussianBlur(radius=12))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def pdf_bytes(*, page_count: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload_question_image(client, cookies, raw: bytes, *, filename="question.png"):
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": (filename, raw, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


class _FakeUploadSession:
    def __init__(self) -> None:
        self.asset: UploadedAsset | None = None
        self.rolled_back = False

    def add(self, asset: UploadedAsset) -> None:
        asset.id = str(uuid4())
        asset.created_at = datetime.now(timezone.utc)
        self.asset = asset

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, _asset: UploadedAsset) -> None:
        return None


class _ControlledCommitSession(_FakeUploadSession):
    def __init__(
        self,
        *,
        commit_started: asyncio.Event,
        release_commit: asyncio.Event,
        fail_commit: bool,
    ) -> None:
        super().__init__()
        self.commit_started = commit_started
        self.release_commit = release_commit
        self.fail_commit = fail_commit
        self.committed = False

    async def commit(self) -> None:
        self.commit_started.set()
        await self.release_commit.wait()
        if self.fail_commit:
            raise RuntimeError("commit failed after cancellation")
        self.committed = True


def _direct_upload_request(client, *, semaphore: asyncio.Semaphore):
    settings = client.app.state.settings.model_copy(
        update={"upload_queue_timeout_seconds": 1.0}
    )
    state = SimpleNamespace(
        settings=settings,
        upload_semaphore=semaphore,
        upload_rate_limiter=DualWindowRateLimiter(
            minute_limit=100,
            hour_limit=100,
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_uploaded_asset_table_is_registered():
    assert "uploaded_assets" in Base.metadata.tables
    assert UploadedAsset.__tablename__ == "uploaded_assets"


@pytest.mark.parametrize(
    ("image_format", "canonical_mime", "suffix"),
    [
        ("JPEG", "image/jpeg", ".jpg"),
        ("PNG", "image/png", ".png"),
        ("BMP", "image/bmp", ".bmp"),
    ],
)
def test_accepts_supported_images_by_decoded_content(
    client, image_format, canonical_mime, suffix
):
    cookies = register(client, f"upload-{image_format.lower()}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={
            "file": (
                "misleading.webp",
                image_bytes(image_format),
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["mime_type"] == canonical_mime
    assert payload["storage_name"].endswith(suffix)
    assert payload["file_kind"] == "image"
    assert payload["width"] == 640
    assert payload["height"] == 800
    assert payload["page_count"] is None
    assert payload["warnings"] == []


@pytest.mark.parametrize(
    ("size", "should_warn"),
    [
        ((600, 800), False),
        ((800, 600), False),
        ((599, 800), True),
        ((800, 599), True),
    ],
)
def test_resolution_warning_uses_orientation_independent_600_by_800_boundary(
    client, size, should_warn
):
    cookies = register(client, f"upload-resolution-{size[0]}-{size[1]}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={
            "file": (
                "question.png",
                quality_image_bytes("clear", size=size),
                "image/png",
            )
        },
    )

    assert response.status_code == 201, response.text
    resolution_warnings = [
        warning for warning in response.json()["warnings"] if "分辨率" in warning
    ]
    assert bool(resolution_warnings) is should_warn


@pytest.mark.parametrize(
    ("quality", "expected_warning"),
    [
        ("clear", None),
        ("blurry", "图片可能模糊，建议重新拍摄或扫描"),
        ("dark", "图片可能过暗，建议提高光线或亮度"),
        ("bright", "图片可能过曝，建议避免强光并重新拍摄"),
    ],
)
def test_returns_deterministic_image_quality_warnings(
    client, quality, expected_warning
):
    cookies = register(client, f"upload-quality-{quality}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", quality_image_bytes(quality), "image/png")},
    )

    assert response.status_code == 201, response.text
    quality_warnings = [
        warning
        for warning in response.json()["warnings"]
        if any(label in warning for label in ("可能模糊", "可能过暗", "可能过曝"))
    ]
    if expected_warning is None:
        assert quality_warnings == []
    else:
        assert expected_warning in quality_warnings


def test_accepts_pdf_and_returns_page_count(client):
    cookies = register(client, "upload-pdf@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.jpg", pdf_bytes(page_count=2), "image/jpeg")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["mime_type"] == "application/pdf"
    assert payload["storage_name"].endswith(".pdf")
    assert payload["file_kind"] == "pdf"
    assert payload["page_count"] == 2
    assert payload["width"] is None
    assert payload["height"] is None
    assert isinstance(payload["warnings"], list)


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        pytest.param("webp", image_bytes("WEBP"), id="webp"),
        pytest.param("gif", image_bytes("GIF"), id="gif"),
        pytest.param(
            "svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', id="svg"
        ),
        pytest.param(
            "heic",
            b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1",
            id="heic",
        ),
        pytest.param("tiff", image_bytes("TIFF"), id="tiff"),
    ],
)
def test_rejects_unsupported_content_even_with_supported_declaration(
    client, label, raw
):
    cookies = register(client, f"upload-{label}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", raw, "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_corrupted_supported_image_by_real_signature(client):
    cookies = register(client, "upload-corrupt-signature@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"\x89PNG\r\n\x1a\ntruncated", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_IMAGE_DECODE_FAILED"


def test_rejects_empty_file(client):
    cookies = register(client, "upload-empty@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_EMPTY_FILE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_empty_filename(client):
    cookies = register(client, "upload-empty-name@example.com")
    boundary = "empty-filename-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename=""\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + png_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_INVALID_FILENAME"
    assert not client.app.state.settings.upload_dir.exists()


@pytest.mark.parametrize("chunked", [False, True])
def test_rejects_oversized_multipart_before_authentication_and_form_parsing(
    client, chunked
):
    boundary = "oversized-ingress-boundary"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="huge.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    raw_budget = 3 * (client.app.state.settings.max_upload_bytes // 4)
    payload = b"x" * (raw_budget + 64 * 1024 + 1)
    body = prefix + payload + suffix
    content = iter((prefix, payload, suffix)) if chunked else body

    response = client.post(
        "/api/v1/uploads/questions",
        content=content,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "OCR_FILE_TOO_LARGE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_invalid_pdf_with_pdf_signature(client):
    cookies = register(client, "upload-invalid-pdf@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.pdf", b"%PDF-1.7\ntruncated", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_INVALID_PDF"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_pypdf_limit_error_as_invalid_pdf(client, monkeypatch):
    cookies = register(client, "upload-pdf-limit@example.com")

    def fail_reader(_stream):
        raise LimitReachedError("object limit reached")

    monkeypatch.setattr("app.services.storage.PdfReader", fail_reader)
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_INVALID_PDF"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_unknown_random_bytes_as_unsupported(client):
    cookies = register(client, "upload-random@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"random bytes", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_when_actual_base64_payload_exceeds_ten_mib(client):
    cookies = register(client, "upload-base64-size@example.com")
    raw = image_bytes("BMP", size=(1800, 1500))
    limit = 10 * 1024 * 1024
    assert len(raw) < limit
    assert len(base64.b64encode(raw)) > limit

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.bmp", raw, "image/bmp")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "OCR_FILE_TOO_LARGE"
    assert not client.app.state.settings.upload_dir.exists()


def test_accepts_when_actual_base64_payload_equals_ten_mib(client):
    cookies = register(client, "upload-base64-boundary@example.com")
    limit = 10 * 1024 * 1024
    raw_size = limit // 4 * 3
    raw = png_bytes().ljust(raw_size, b"\x00")
    assert len(base64.b64encode(raw)) == limit

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", raw, "image/png")},
    )

    assert response.status_code == 201, response.text


def test_save_image_calculates_sha256(client):
    raw = png_bytes()
    upload = UploadFile(file=BytesIO(raw), filename="question.png")

    stored = asyncio.run(
        save_image(
            upload,
            upload_dir=client.app.state.settings.upload_dir,
            max_upload_bytes=client.app.state.settings.max_upload_bytes,
        )
    )

    assert stored.sha256 == hashlib.sha256(raw).hexdigest()
    assert (
        client.app.state.settings.upload_dir / stored.storage_name
    ).read_bytes() == raw


def test_save_image_offloads_inspection_hash_and_write_from_event_loop(
    client, monkeypatch
):
    raw = png_bytes()
    upload = UploadFile(file=BytesIO(raw), filename="question.png")
    worker_threads: dict[str, int] = {}
    original_inspect_file = storage._inspect_file
    original_sha256 = hashlib.sha256
    original_write_bytes = Path.write_bytes

    def inspect_file_in_worker(payload: bytes):
        worker_threads["inspect"] = threading.get_ident()
        return original_inspect_file(payload)

    def sha256_in_worker(payload: bytes = b""):
        worker_threads["sha256"] = threading.get_ident()
        return original_sha256(payload)

    def write_bytes_in_worker(path: Path, payload: bytes):
        worker_threads["write"] = threading.get_ident()
        return original_write_bytes(path, payload)

    monkeypatch.setattr(storage, "_inspect_file", inspect_file_in_worker)
    monkeypatch.setattr(storage.hashlib, "sha256", sha256_in_worker)
    monkeypatch.setattr(Path, "write_bytes", write_bytes_in_worker)

    async def exercise() -> int:
        event_loop_thread = threading.get_ident()
        await save_image(
            upload,
            upload_dir=client.app.state.settings.upload_dir,
            max_upload_bytes=client.app.state.settings.max_upload_bytes,
        )
        return event_loop_thread

    event_loop_thread = asyncio.run(exercise())

    assert set(worker_threads) == {"inspect", "sha256", "write"}
    assert all(
        worker_thread != event_loop_thread for worker_thread in worker_threads.values()
    )


def test_save_image_cancellation_waits_for_worker_and_cleans_written_file(
    client, monkeypatch
):
    raw = png_bytes()
    upload = UploadFile(file=BytesIO(raw), filename="question.png")
    worker_persisted = threading.Event()
    release_worker = threading.Event()
    cleanup_threads: list[int] = []
    original_process = storage._inspect_hash_and_persist
    original_unlink = Path.unlink

    def persist_then_wait(payload: bytes, upload_dir: Path):
        result = original_process(payload, upload_dir)
        worker_persisted.set()
        assert release_worker.wait(timeout=5)
        return result

    def track_unlink(path: Path, *args, **kwargs):
        if path.parent == client.app.state.settings.upload_dir:
            cleanup_threads.append(threading.get_ident())
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(storage, "_inspect_hash_and_persist", persist_then_wait)
    monkeypatch.setattr(Path, "unlink", track_unlink)

    async def scenario():
        event_loop_thread = threading.get_ident()
        pending = asyncio.create_task(
            save_image(
                upload,
                upload_dir=client.app.state.settings.upload_dir,
                max_upload_bytes=client.app.state.settings.max_upload_bytes,
            )
        )
        assert await asyncio.to_thread(worker_persisted.wait, 2)
        assert len(list(client.app.state.settings.upload_dir.iterdir())) == 1

        pending.cancel()
        await asyncio.sleep(0)
        try:
            assert not pending.done()
        finally:
            release_worker.set()

        with pytest.raises(asyncio.CancelledError):
            await pending
        assert list(client.app.state.settings.upload_dir.iterdir()) == []
        assert cleanup_threads
        assert all(thread_id != event_loop_thread for thread_id in cleanup_threads)

    asyncio.run(scenario())


def test_rejects_non_image(client):
    cookies = register(client, "upload-type@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"


def test_rejects_oversized_image_before_writing(client):
    cookies = register(client, "upload-size@example.com")
    client.app.state.settings.max_upload_bytes = 10
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "OCR_FILE_TOO_LARGE"
    assert not client.app.state.settings.upload_dir.exists()


@pytest.mark.parametrize(
    ("minute_limit", "hour_limit", "label"),
    [(1, 10, "minute"), (10, 1, "hour")],
)
def test_upload_rate_limit_is_scoped_to_user_with_stable_chinese_429(
    client, minute_limit, hour_limit, label
):
    first_user = register(client, f"upload-rate-{label}-first@example.com")
    second_user = register(client, f"upload-rate-{label}-second@example.com")
    client.app.state.upload_rate_limiter = DualWindowRateLimiter(
        minute_limit=minute_limit,
        hour_limit=hour_limit,
    )

    accepted = client.post(
        "/api/v1/uploads/questions",
        cookies=first_user,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )
    limited = client.post(
        "/api/v1/uploads/questions",
        cookies=first_user,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )
    other_user = client.post(
        "/api/v1/uploads/questions",
        cookies=second_user,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )

    assert accepted.status_code == 201
    assert limited.status_code == 429
    assert limited.json()["code"] == "UPLOAD_RATE_LIMITED"
    assert limited.json()["message"] == "上传请求过于频繁，请稍后再试"
    assert other_user.status_code == 201


def test_upload_processing_has_global_concurrency_bound_and_queue_timeout(
    client, monkeypatch
):
    cookies = register(client, "upload-concurrency@example.com")
    client.app.state.upload_semaphore = asyncio.Semaphore(2)
    # Keep this test focused on the post-auth processing queue.  The separate
    # pre-auth ingress middleware normally admits the same number of requests.
    client.app.state.upload_ingress_semaphore.release()
    client.app.state.settings.upload_queue_timeout_seconds = 0.1
    raw = png_bytes().ljust(1024 * 1024, b"\x00")
    release_processing = threading.Event()
    two_entered = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0
    original_process = storage._inspect_hash_and_persist

    def slow_process(payload: bytes, upload_dir: Path):
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                two_entered.set()
        try:
            assert release_processing.wait(timeout=5)
            return original_process(payload, upload_dir)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(storage, "_inspect_hash_and_persist", slow_process)

    def upload_once():
        return client.post(
            "/api/v1/uploads/questions",
            cookies=cookies,
            files={"file": ("large-question.png", raw, "image/png")},
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(upload_once)
        second = executor.submit(upload_once)
        assert two_entered.wait(timeout=5)
        queued = executor.submit(upload_once)
        time.sleep(0.2)
        release_processing.set()
        responses = [first.result(), second.result(), queued.result()]

    assert maximum_active == 2
    assert sorted(response.status_code for response in responses) == [201, 201, 429]
    limited = next(response for response in responses if response.status_code == 429)
    assert limited.json()["code"] == "UPLOAD_RATE_LIMITED"
    assert limited.json()["message"] == "上传服务繁忙，请稍后重试"


def test_cancelled_upload_holds_semaphore_until_worker_really_stops(
    client, monkeypatch
):
    raw = png_bytes()
    first_worker_persisted = threading.Event()
    release_first_worker = threading.Event()
    second_worker_started = threading.Event()
    counter_lock = threading.Lock()
    original_process = storage._inspect_hash_and_persist
    calls = 0
    active = 0
    maximum_active = 0

    def controlled_process(payload: bytes, upload_dir: Path):
        nonlocal calls, active, maximum_active
        with counter_lock:
            calls += 1
            call_number = calls
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            result = original_process(payload, upload_dir)
            if call_number == 1:
                first_worker_persisted.set()
                assert release_first_worker.wait(timeout=5)
            else:
                second_worker_started.set()
            return result
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(storage, "_inspect_hash_and_persist", controlled_process)

    async def scenario():
        semaphore = asyncio.Semaphore(1)
        request = _direct_upload_request(client, semaphore=semaphore)
        user = SimpleNamespace(id="upload-cancellation-user")
        first = asyncio.create_task(
            upload_question_image_route(
                file=UploadFile(file=BytesIO(raw), filename="first.png"),
                current_user=user,
                session=_FakeUploadSession(),
                request=request,
            )
        )
        assert await asyncio.to_thread(first_worker_persisted.wait, 2)
        first.cancel()
        await asyncio.sleep(0)

        second = asyncio.create_task(
            upload_question_image_route(
                file=UploadFile(file=BytesIO(raw), filename="second.png"),
                current_user=user,
                session=_FakeUploadSession(),
                request=request,
            )
        )
        await asyncio.sleep(0.1)
        try:
            assert semaphore.locked()
            assert not second_worker_started.is_set()
            assert maximum_active == 1
        finally:
            release_first_worker.set()

        with pytest.raises(asyncio.CancelledError):
            await first
        result = await second
        assert result.original_name == "second.png"
        assert second_worker_started.is_set()
        assert maximum_active == 1

    asyncio.run(scenario())


def test_rejects_unsupported_image_format(client):
    cookies = register(client, "upload-format@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.gif", b"GIF89a", "image/gif")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"


def test_rejects_original_filename_that_exceeds_metadata_limit(client):
    cookies = register(client, "upload-name@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("a" * 501, png_bytes(), "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "filename_too_long"


def test_rejects_control_characters_in_original_filename(client):
    upload = UploadFile(file=BytesIO(png_bytes()), filename="question\x00.png")
    with pytest.raises(InvalidFilename):
        asyncio.run(
            save_image(
                upload,
                upload_dir=client.app.state.settings.upload_dir,
                max_upload_bytes=client.app.state.settings.max_upload_bytes,
            )
        )


def test_rejects_images_above_pixel_safety_limit():
    image = Image.new("1", (5001, 5001), 0)
    output = BytesIO()
    image.save(output, format="PNG")
    with pytest.raises(InvalidImage):
        inspect_image(output.getvalue())


def test_upload_download_is_scoped_and_uses_random_extension(client):
    first = register(client, "upload-first@example.com")
    uploaded = upload_question_image(
        client, first, png_bytes(), filename="../../evil.txt"
    )

    assert uploaded["mime_type"] == "image/png"
    assert uploaded["original_name"] == "../../evil.txt"
    assert uploaded["storage_name"].endswith(".png")
    assert "/" not in uploaded["storage_name"]
    storage_id = UUID(Path(uploaded["storage_name"]).stem)
    assert storage_id.version == 4

    download = client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=first)
    assert download.status_code == 200
    assert download.content == png_bytes()
    assert download.headers["content-type"].startswith("image/png")

    second = register(client, "upload-second@example.com")
    assert (
        client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=second).status_code
        == 404
    )


def test_database_commit_failure_removes_persisted_file(client, monkeypatch):
    cookies = register(client, "upload-commit-failure@example.com")

    async def fail_commit(_session):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 500
    upload_dir = client.app.state.settings.upload_dir
    assert upload_dir.is_dir()
    assert list(upload_dir.iterdir()) == []


def test_database_commit_failure_offloads_file_cleanup(client, monkeypatch):
    cookies = register(client, "upload-commit-cleanup-thread@example.com")
    upload_dir = client.app.state.settings.upload_dir
    event_loop_threads: list[int] = []
    cleanup_threads: list[int] = []
    original_unlink = Path.unlink

    async def fail_commit(_session):
        event_loop_threads.append(threading.get_ident())
        raise RuntimeError("commit failed")

    def track_unlink(path: Path, *args, **kwargs):
        if path.parent == upload_dir:
            cleanup_threads.append(threading.get_ident())
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    monkeypatch.setattr(Path, "unlink", track_unlink)

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 500
    assert len(event_loop_threads) == 1
    assert cleanup_threads
    assert all(thread_id != event_loop_threads[0] for thread_id in cleanup_threads)


def test_commit_cancellation_waits_for_failure_then_cleans_file_and_rolls_back(client):
    async def scenario():
        commit_started = asyncio.Event()
        release_commit = asyncio.Event()
        session = _ControlledCommitSession(
            commit_started=commit_started,
            release_commit=release_commit,
            fail_commit=True,
        )
        request = _direct_upload_request(client, semaphore=asyncio.Semaphore(1))
        pending = asyncio.create_task(
            upload_question_image_route(
                file=UploadFile(file=BytesIO(png_bytes()), filename="question.png"),
                current_user=SimpleNamespace(id="commit-failure-cancel-user"),
                session=session,
                request=request,
            )
        )
        await asyncio.wait_for(commit_started.wait(), timeout=2)
        assert len(list(client.app.state.settings.upload_dir.iterdir())) == 1

        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release_commit.set()

        with pytest.raises(asyncio.CancelledError):
            await pending
        assert session.committed is False
        assert session.rolled_back is True
        assert list(client.app.state.settings.upload_dir.iterdir()) == []

    asyncio.run(scenario())


def test_commit_cancellation_waits_for_success_and_preserves_consistent_asset(client):
    async def scenario():
        commit_started = asyncio.Event()
        release_commit = asyncio.Event()
        session = _ControlledCommitSession(
            commit_started=commit_started,
            release_commit=release_commit,
            fail_commit=False,
        )
        request = _direct_upload_request(client, semaphore=asyncio.Semaphore(1))
        pending = asyncio.create_task(
            upload_question_image_route(
                file=UploadFile(file=BytesIO(png_bytes()), filename="question.png"),
                current_user=SimpleNamespace(id="commit-success-cancel-user"),
                session=session,
                request=request,
            )
        )
        await asyncio.wait_for(commit_started.wait(), timeout=2)

        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release_commit.set()

        with pytest.raises(asyncio.CancelledError):
            await pending
        assert session.committed is True
        assert session.rolled_back is False
        assert len(list(client.app.state.settings.upload_dir.iterdir())) == 1

    asyncio.run(scenario())
