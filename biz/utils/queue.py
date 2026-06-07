import atexit
import os
import signal
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Any, Callable

from biz.utils.log import logger


class QueueStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED_QUEUE_FULL = "rejected_queue_full"


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
        if value <= 0:
            raise ValueError("must be greater than 0")
        return value
    except ValueError:
        logger.warning(
            "Invalid %s=%s, fallback to default=%s", name, raw_value, default
        )
        return default


MAX_WORKERS = _get_int_env("WORKER_MAX_WORKERS", 4)
MAX_QUEUE_SIZE = _get_int_env("WORKER_MAX_QUEUE_SIZE", 64)

_MAX_INFLIGHT = MAX_WORKERS + MAX_QUEUE_SIZE
_slot_semaphore = BoundedSemaphore(_MAX_INFLIGHT)
_executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS, thread_name_prefix="webhook-worker"
)

logger.info(
    "Initialized worker queue: max_workers=%d, max_queue_size=%d, reject_policy=reject",
    MAX_WORKERS,
    MAX_QUEUE_SIZE,
)

_shutdown_lock = Lock()
_shutdown_done = False


def _shutdown_executor(reason: str = "unknown") -> None:
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True
    logger.info("Shutting down worker executor, reason=%s", reason)
    _executor.shutdown(wait=False, cancel_futures=True)


def _register_signal_handlers() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous_handler = signal.getsignal(sig)

            def _handler(signum: int, frame: Any, prev: Any = previous_handler) -> None:
                _shutdown_executor(reason=f"signal:{signum}")
                if callable(prev):
                    prev(signum, frame)

            signal.signal(sig, _handler)
        except (ValueError, RuntimeError):
            # Ignore registration failure in non-main-thread environments
            logger.warning("Failed to register signal handler: signal=%s", sig)


@atexit.register
def _atexit_shutdown() -> None:
    _shutdown_executor(reason="atexit")


_register_signal_handlers()


def _safe_run(
    function: Callable[..., Any],
    task_context: dict[str, Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    try:
        function(*args, **kwargs)
    except Exception:
        logger.exception(
            "Unhandled error in async worker task, context=%s", task_context
        )
    finally:
        _slot_semaphore.release()


def handle_queue(
    function: Callable[..., Any],
    *args: Any,
    task_context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> QueueStatus:
    """
    Submit a task to the thread pool.
    Return value:
    - QueueStatus.ACCEPTED: Task successfully enqueued
    - QueueStatus.REJECTED_QUEUE_FULL: Task rejected (queue is full)
    """
    context = task_context or {}

    accepted = _slot_semaphore.acquire(blocking=False)
    if not accepted:
        logger.warning(
            "Worker queue is full, reject task. max_workers=%d, max_queue_size=%d, context=%s",
            MAX_WORKERS,
            MAX_QUEUE_SIZE,
            context,
        )
        return QueueStatus.REJECTED_QUEUE_FULL

    _executor.submit(_safe_run, function, context, *args, **kwargs)
    return QueueStatus.ACCEPTED
