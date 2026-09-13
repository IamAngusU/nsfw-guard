from __future__ import annotations

import pytest

from nsfw_guard.errors import InvalidInputError
from nsfw_guard.folder_scan import recommend_inference_threads


def test_cpu_thread_auto_plan_divides_physical_cores_across_workers() -> None:
    assert (
        recommend_inference_threads(
            provider="cpu",
            requested_threads=0,
            requested_workers=None,
            physical_cpu_count=16,
        )
        == 4
    )
    assert (
        recommend_inference_threads(
            provider="cpu",
            requested_threads=0,
            requested_workers=8,
            physical_cpu_count=16,
        )
        == 2
    )


def test_explicit_and_gpu_thread_settings_are_not_rewritten() -> None:
    assert (
        recommend_inference_threads(
            provider="cpu",
            requested_threads=7,
            requested_workers=None,
            physical_cpu_count=16,
        )
        == 7
    )
    assert (
        recommend_inference_threads(
            provider="cuda",
            requested_threads=0,
            requested_workers=None,
            physical_cpu_count=16,
        )
        == 0
    )


def test_negative_thread_setting_is_rejected_before_model_load() -> None:
    with pytest.raises(InvalidInputError, match="zero or greater"):
        recommend_inference_threads(
            provider="cpu",
            requested_threads=-1,
            requested_workers=None,
            physical_cpu_count=16,
        )
