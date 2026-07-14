from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class TaskOutcome(Generic[T]):
    value: T | None
    error: BaseException | None
    caller_cancelled: bool


async def await_task_outcome(task: asyncio.Task[T]) -> TaskOutcome[T]:
    """Wait for an owned task to really finish without losing caller cancellation."""

    caller_cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                caller_cancelled = True
            else:
                break
        except Exception:
            # The task's exception is collected below after it reaches a
            # terminal state.  Keeping it owned avoids "never retrieved" logs.
            pass

    try:
        value = task.result()
    except BaseException as error:
        return TaskOutcome(None, error, caller_cancelled)
    return TaskOutcome(value, None, caller_cancelled)
