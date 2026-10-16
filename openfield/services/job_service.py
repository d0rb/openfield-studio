from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class Job:
    id: str
    kind: str
    status: str = "created"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: dict[str, Any] = field(default_factory=dict)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str, result: dict[str, Any] | None = None) -> Job:
        job = Job(uuid4().hex, kind, result=result or {})
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())
