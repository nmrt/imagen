from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# JobStatus and JobRecord could be imported from schemas.py
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobRecord:
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None


class JobQueue(Protocol):
    def submit(self, task: Callable[[], Awaitable[dict[str, Any]]]) -> str: ...
    def get(self, job_id: str) -> JobRecord | None: ...


# Async queue-compatible boundary that can be easily swapped for Celery/Redis later
@dataclass
class InMemoryJobQueue:
    jobs: Dict[str, JobRecord] = field(default_factory=dict)

    def submit(self, task: Callable[[], Awaitable[dict[str, Any]]]) -> str:
        job_id = str(uuid4())
        now = _utc_now()
        self.jobs[job_id] = JobRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )

        async def runner() -> None:
            job = self.jobs[job_id]
            job.status = JobStatus.RUNNING
            job.updated_at = _utc_now()
            try:
                job.result = await task()
                job.status = JobStatus.SUCCEEDED
            except Exception as exc:  # pragma: no cover - defensive catch
                job.error = str(exc)
                job.status = JobStatus.FAILED
            finally:
                job.updated_at = _utc_now()

        asyncio.create_task(runner())
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)
