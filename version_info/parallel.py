from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_bounded_ordered(items: Sequence[T], fn: Callable[[T], R], *, max_workers: int) -> list[R]:
    worker_count = max(1, min(max_workers, len(items)))
    if worker_count == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(fn, item) for item in items]
        return [future.result() for future in futures]
