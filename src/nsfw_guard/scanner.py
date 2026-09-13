from __future__ import annotations

import hashlib
import hmac
import io
import os
import stat
import threading
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .backend import ImageBackend, Prediction
from .contracts import ArtifactEvidence, ScanResult, TimingEvidence, Verdict
from .errors import (
    ArtifactTooLargeError,
    DigestMismatchError,
    GuardError,
    InvalidInputError,
    SourceChangedError,
    UnsupportedMediaError,
)
from .policy import PolicyConfig, evaluate_score

READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ScanLimits:
    max_bytes: int = 25 * 1024 * 1024
    max_pixels: int = 40_000_000
    allowed_formats: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.max_pixels <= 0:
            raise InvalidInputError("Scan limits must be positive.")


@dataclass(frozen=True, slots=True)
class _DecodedImage:
    images: tuple[Image.Image, ...]
    width: int
    height: int
    media_format: str
    animated: bool
    transparency_dual_scan: bool


def read_bounded_image_path(path: Path, limits: ScanLimits) -> tuple[bytes, str]:
    """Read one stable regular file, bounded by the same limits as the base scan."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise InvalidInputError("The image path could not be opened.") from exc
    if stat.S_ISLNK(before.st_mode):
        raise InvalidInputError("Symbolic-link image paths are not accepted.")
    if not stat.S_ISREG(before.st_mode):
        raise InvalidInputError("The image path is not a regular file.")
    if before.st_size > limits.max_bytes:
        raise ArtifactTooLargeError(
            "The encoded image exceeds the configured byte limit.",
            details={"max_bytes": limits.max_bytes, "actual_bytes": before.st_size},
        )

    chunks: list[bytes] = []
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not os.path.samestat(before, opened):
                raise SourceChangedError("The image changed before it could be read.")
            while True:
                chunk = handle.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > limits.max_bytes:
                    raise ArtifactTooLargeError(
                        "The encoded image exceeded its byte limit while being read.",
                        details={"max_bytes": limits.max_bytes},
                    )
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
    except GuardError:
        raise
    except OSError as exc:
        raise InvalidInputError("The image could not be read.") from exc
    if total != opened.st_size or after.st_size != opened.st_size:
        raise SourceChangedError("The image size changed while it was being read.")
    return b"".join(chunks), digest.hexdigest()


class Scanner:
    def __init__(
        self,
        *,
        backend: ImageBackend,
        policy: PolicyConfig,
        limits: ScanLimits | None = None,
        cache_entries: int = 512,
    ) -> None:
        if cache_entries < 0:
            raise InvalidInputError("Cache entries must be zero or greater.")
        self.backend = backend
        self.policy = policy
        self.limits = limits or ScanLimits()
        self._cache_entries = cache_entries
        self._cache: OrderedDict[str, Prediction] = OrderedDict()
        self._cache_lock = threading.Lock()

    def scan_path(
        self,
        path: str | Path,
        *,
        claimed_sha256: str | None = None,
        policy: PolicyConfig | None = None,
    ) -> ScanResult:
        started = time.perf_counter()
        read_started = time.perf_counter()
        payload, digest = self._read_path(Path(path))
        read_ms = (time.perf_counter() - read_started) * 1000.0
        return self._scan_payload(
            payload,
            digest,
            started=started,
            read_ms=read_ms,
            claimed_sha256=claimed_sha256,
            policy=policy or self.policy,
        )

    def scan_bytes(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        claimed_sha256: str | None = None,
        policy: PolicyConfig | None = None,
    ) -> ScanResult:
        started = time.perf_counter()
        data = bytes(payload)
        if len(data) > self.limits.max_bytes:
            raise ArtifactTooLargeError(
                "The encoded image exceeds the configured byte limit.",
                details={"max_bytes": self.limits.max_bytes, "actual_bytes": len(data)},
            )
        digest = hashlib.sha256(data).hexdigest()
        return self._scan_payload(
            data,
            digest,
            started=started,
            read_ms=0.0,
            claimed_sha256=claimed_sha256,
            policy=policy or self.policy,
        )

    def _read_path(self, path: Path) -> tuple[bytes, str]:
        return read_bounded_image_path(path, self.limits)

    def _scan_payload(
        self,
        payload: bytes,
        digest: str,
        *,
        started: float,
        read_ms: float,
        claimed_sha256: str | None,
        policy: PolicyConfig,
    ) -> ScanResult:
        self._check_claimed_digest(digest, claimed_sha256)
        decode_started = time.perf_counter()
        decoded = self._decode(payload)
        decode_ms = (time.perf_counter() - decode_started) * 1000.0
        artifact = ArtifactEvidence(
            sha256=digest,
            byte_length=len(payload),
            width=decoded.width,
            height=decoded.height,
            media_format=decoded.media_format,
            animated=decoded.animated,
        )

        if decoded.animated:
            total_ms = (time.perf_counter() - started) * 1000.0
            return ScanResult(
                verdict=Verdict.REVIEW,
                reason_codes=("animated_media_requires_frame_aware_scan",),
                scores=None,
                artifact=artifact,
                model=self.backend.evidence,
                policy=policy.to_dict(),
                timing=TimingEvidence(read_ms, decode_ms, 0.0, 0.0, total_ms, False),
            )

        cached = self._cache_get(digest)
        cache_hit = cached is not None
        if cached is None:
            predictions = [self.backend.predict(image) for image in decoded.images]
            prediction = max(predictions, key=lambda item: item.nsfw_score)
            self._cache_put(digest, prediction)
            preprocess_ms = sum(item.preprocess_ms for item in predictions)
            inference_ms = sum(item.inference_ms for item in predictions)
        else:
            prediction = cached
            preprocess_ms = 0.0
            inference_ms = 0.0

        verdict, reasons = evaluate_score(prediction.nsfw_score, policy)
        if decoded.transparency_dual_scan:
            reasons = (*reasons, "transparent_image_scanned_on_dark_and_light_backgrounds")
        total_ms = (time.perf_counter() - started) * 1000.0
        return ScanResult(
            verdict=verdict,
            reason_codes=reasons,
            scores={"nsfw": prediction.nsfw_score, "safe": prediction.safe_score},
            artifact=artifact,
            model=self.backend.evidence,
            policy=policy.to_dict(),
            timing=TimingEvidence(
                read_ms,
                decode_ms,
                preprocess_ms,
                inference_ms,
                total_ms,
                cache_hit,
            ),
        )

    def _decode(self, payload: bytes) -> _DecodedImage:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(payload)) as source:
                    media_format = (source.format or "").upper()
                    if media_format not in self.limits.allowed_formats:
                        raise UnsupportedMediaError(
                            "The image format is not supported.",
                            details={"allowed_formats": sorted(self.limits.allowed_formats)},
                        )
                    width, height = source.size
                    if width <= 0 or height <= 0 or width * height > self.limits.max_pixels:
                        raise ArtifactTooLargeError(
                            "The decoded image exceeds the configured pixel limit.",
                            details={
                                "max_pixels": self.limits.max_pixels,
                                "actual_pixels": width * height,
                            },
                        )
                    animated = (
                        bool(getattr(source, "is_animated", False))
                        or int(getattr(source, "n_frames", 1)) > 1
                    )
                    if animated:
                        return _DecodedImage((), width, height, media_format, True, False)

                    oriented = ImageOps.exif_transpose(source)
                    has_alpha = oriented.mode in {"LA", "PA", "RGBA"} or (
                        "transparency" in source.info
                    )
                    if has_alpha:
                        rgba = oriented.convert("RGBA")
                        # An alpha channel can be fully opaque (common in screenshots).
                        # Only actual transparency needs two background variants.
                        has_transparency = rgba.getchannel("A").getextrema()[0] < 255  # type: ignore[no-untyped-call]
                        if has_transparency:
                            images = tuple(
                                Image.alpha_composite(
                                    Image.new("RGBA", rgba.size, color), rgba
                                ).convert("RGB")
                                for color in ((0, 0, 0, 255), (255, 255, 255, 255))
                            )
                        else:
                            images = (rgba.convert("RGB"),)
                    else:
                        images = (oriented.convert("RGB"),)
                        has_transparency = False
                    for image in images:
                        image.load()
                    return _DecodedImage(
                        images,
                        width,
                        height,
                        media_format,
                        False,
                        has_transparency,
                    )
        except GuardError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ArtifactTooLargeError(
                "Pillow rejected the image as a decompression bomb."
            ) from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise UnsupportedMediaError("The payload is not a valid supported image.") from exc

    @staticmethod
    def _check_claimed_digest(actual: str, claimed: str | None) -> None:
        if claimed is None:
            return
        normalized = claimed.lower()
        malformed = len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        )
        if malformed:
            raise InvalidInputError("The claimed SHA-256 is malformed.")
        if not hmac.compare_digest(actual, normalized):
            raise DigestMismatchError(
                "The image bytes do not match the claimed SHA-256.",
                details={"claimed_sha256": normalized, "actual_sha256": actual},
            )

    def _cache_get(self, digest: str) -> Prediction | None:
        if self._cache_entries == 0:
            return None
        with self._cache_lock:
            prediction = self._cache.get(digest)
            if prediction is not None:
                self._cache.move_to_end(digest)
            return prediction

    def _cache_put(self, digest: str, prediction: Prediction) -> None:
        if self._cache_entries == 0:
            return
        with self._cache_lock:
            self._cache[digest] = prediction
            self._cache.move_to_end(digest)
            while len(self._cache) > self._cache_entries:
                self._cache.popitem(last=False)
