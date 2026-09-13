import hashlib
import io

import pytest
from PIL import Image

from nsfw_guard.backend import Prediction
from nsfw_guard.contracts import Verdict
from nsfw_guard.errors import ArtifactTooLargeError, DigestMismatchError, UnsupportedMediaError
from nsfw_guard.policy import get_policy
from nsfw_guard.scanner import ScanLimits, Scanner


class FakeBackend:
    def __init__(self, scores: list[float]) -> None:
        self.scores = iter(scores)
        self.calls = 0

    @property
    def evidence(self) -> dict[str, object]:
        return {"id": "fake", "artifact_sha256": "0" * 64, "requested_provider": "cpu"}

    def predict(self, image: Image.Image) -> Prediction:
        assert image.mode == "RGB"
        self.calls += 1
        score = next(self.scores)
        return Prediction(score, 1.0 - score, 1.0, 2.0)


def image_bytes(format_name: str = "JPEG", *, alpha: bool = False) -> bytes:
    mode = "RGBA" if alpha else "RGB"
    color = (20, 40, 60, 100) if alpha else (20, 40, 60)
    image = Image.new(mode, (32, 24), color)
    buffer = io.BytesIO()
    image.save(buffer, format=format_name)
    return buffer.getvalue()


def scanner(backend: FakeBackend, *, cache_entries: int = 8) -> Scanner:
    return Scanner(
        backend=backend,
        policy=get_policy("balanced-v1"),
        cache_entries=cache_entries,
    )


def test_static_image_produces_bound_evidence() -> None:
    payload = image_bytes()
    backend = FakeBackend([0.1])
    result = scanner(backend).scan_bytes(payload)
    assert result.verdict is Verdict.ALLOW
    assert result.artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.artifact.media_format == "JPEG"
    assert result.scores == {"nsfw": 0.1, "safe": 0.9}
    assert backend.calls == 1


def test_digest_mismatch_stops_before_inference() -> None:
    backend = FakeBackend([0.1])
    with pytest.raises(DigestMismatchError):
        scanner(backend).scan_bytes(image_bytes(), claimed_sha256="0" * 64)
    assert backend.calls == 0


def test_encoded_byte_limit_stops_before_decode() -> None:
    backend = FakeBackend([0.1])
    limited = Scanner(
        backend=backend,
        policy=get_policy("balanced-v1"),
        limits=ScanLimits(max_bytes=8, max_pixels=1000),
    )
    with pytest.raises(ArtifactTooLargeError):
        limited.scan_bytes(image_bytes())
    assert backend.calls == 0


def test_animated_image_is_reviewed_without_single_frame_claim() -> None:
    first = Image.new("RGB", (16, 16), "white")
    second = Image.new("RGB", (16, 16), "black")
    buffer = io.BytesIO()
    first.save(buffer, format="WEBP", save_all=True, append_images=[second], duration=100)
    backend = FakeBackend([0.1])
    result = scanner(backend).scan_bytes(buffer.getvalue())
    assert result.verdict is Verdict.REVIEW
    assert result.scores is None
    assert result.reason_codes == ("animated_media_requires_frame_aware_scan",)
    assert backend.calls == 0


def test_transparency_is_scanned_on_dark_and_light_backgrounds() -> None:
    backend = FakeBackend([0.1, 0.9])
    result = scanner(backend).scan_bytes(image_bytes("PNG", alpha=True))
    assert result.verdict is Verdict.BLOCK
    assert result.scores == {"nsfw": 0.9, "safe": pytest.approx(0.1)}
    assert backend.calls == 2
    assert "transparent_image_scanned_on_dark_and_light_backgrounds" in result.reason_codes


def test_memory_cache_avoids_repeated_inference() -> None:
    payload = image_bytes()
    backend = FakeBackend([0.2])
    subject = scanner(backend)
    first = subject.scan_bytes(payload)
    second = subject.scan_bytes(payload)
    assert first.timing.cache_hit is False
    assert second.timing.cache_hit is True
    assert backend.calls == 1


def test_invalid_payload_never_becomes_allow() -> None:
    with pytest.raises(UnsupportedMediaError):
        scanner(FakeBackend([0.1])).scan_bytes(b"not an image")
