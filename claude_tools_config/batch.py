from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from .dto import BatchErrorDto, BatchResultDto, ItemKind
from .errors import AppError


class ItemRef(Protocol):
    kind: ItemKind
    id: str


ItemT = TypeVar("ItemT", bound=ItemRef)


def run_batch(items: Sequence[ItemT], apply: Callable[[ItemT], None]) -> BatchResultDto:
    applied = 0
    errors: list[BatchErrorDto] = []
    for item in items:
        try:
            apply(item)
            applied += 1
        except AppError as error:
            errors.append(BatchErrorDto(kind=item.kind, id=item.id, message=error.message))
    return BatchResultDto(applied=applied, errors=errors)
