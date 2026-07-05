import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.db.session import AsyncSessionFactory
from backend.app.tool_registry.image_artifact_cleanup import ShellImageArtifactCleanupScheduler
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    build_shell_image_artifact_object_store,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore


@dataclass(frozen=True)
class ShellImageArtifactCleanupWorkerResult:
    claimed_count: int
    succeeded_count: int
    failed_count: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "claimed_count": self.claimed_count,
                "succeeded_count": self.succeeded_count,
                "failed_count": self.failed_count,
            },
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class ShellImageArtifactCleanupScheduleWorker:
    session_factory: async_sessionmaker[AsyncSession]
    object_store_factory: Callable[[], ShellImageArtifactObjectStore]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def run_once(
        self,
        *,
        actor_id: UUID,
        limit: int = 10,
        worker_id: str = "shell-image-artifact-cleanup-worker",
        lease_seconds: int = 300,
    ) -> ShellImageArtifactCleanupWorkerResult:
        async with self.session_factory() as session:
            store = SqlAlchemyToolRegistryStore(session)
            audit_store = SqlAlchemyAuditEventStore(session)
            scheduler = ShellImageArtifactCleanupScheduler(
                store=store,
                object_store_factory=lambda _project_id: self.object_store_factory(),
                clock=self.clock,
            )
            runs = await scheduler.run_due(
                actor_id=actor_id,
                limit=limit,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            for run in runs:
                schedule = await store.get_shell_image_artifact_cleanup_schedule(run.project_id)
                await audit_store.record_project_event(
                    project_id=run.project_id,
                    actor_id=actor_id,
                    action="tool_registry.shell_image_artifact.cleanup_schedule.run",
                    target_type="tool_registry_image_admission_artifact_cleanup_schedule",
                    target_id=str(schedule.id if schedule is not None else run.id),
                    result="failure" if run.status == "failed" else "success",
                    risk_level="medium" if run.status == "failed" else "low",
                    metadata={
                        "worker_id": worker_id,
                        "run_id": str(run.id),
                        "dry_run": run.dry_run,
                        "status": run.status,
                        "candidate_count": run.candidate_count,
                        "deleted_count": run.deleted_count,
                        "failed_count": run.failed_count,
                        "retained_count": run.retained_count,
                    },
                )
        return ShellImageArtifactCleanupWorkerResult(
            claimed_count=len(runs),
            succeeded_count=sum(1 for run in runs if run.status == "succeeded"),
            failed_count=sum(1 for run in runs if run.status == "failed"),
        )


async def run_once_from_settings(
    *,
    actor_id: UUID,
    limit: int = 10,
    worker_id: str = "shell-image-artifact-cleanup-worker",
    lease_seconds: int = 300,
) -> ShellImageArtifactCleanupWorkerResult:
    from backend.app.core.settings import AppSettings

    settings = AppSettings()
    worker = ShellImageArtifactCleanupScheduleWorker(
        session_factory=AsyncSessionFactory,
        object_store_factory=lambda: build_shell_image_artifact_object_store(settings.s3),
    )
    return await worker.run_once(
        actor_id=actor_id,
        limit=limit,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run due shell image artifact cleanup schedules once.",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--limit", default=10, type=int)
    parser.add_argument("--worker-id", default="shell-image-artifact-cleanup-worker")
    parser.add_argument("--lease-seconds", default=300, type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.once:
        raise SystemExit("--once is required for the current worker entrypoint")
    result = asyncio.run(
        run_once_from_settings(
            actor_id=args.actor_id,
            limit=args.limit,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
        )
    )
    print(result.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
