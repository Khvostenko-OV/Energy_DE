from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from urllib.parse import unquote_plus

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import SERVICE_SCHEMA, SOURCE_NAMES
from etl.db_utils import _create_log_table, _ensure_schema
from etl.extract import extract_source_snapshot
from etl.load import ensure_core_tables, load_source_snapshot
from etl.marts import build_marts
from etl.source_data import (
    SourceDataset,
    SourceValidationError,
    inspect_source_gpkg,
)
from etl.transform import transform_source_snapshot


BOUNDARY_KEYS = tuple(f"boundaries/level-{level}.gpkg" for level in range(4))
SOURCE_KEYS = tuple(f"sources/{source}.gpkg" for source in SOURCE_NAMES)
ACCEPTED_KEYS = frozenset(BOUNDARY_KEYS + SOURCE_KEYS)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapConfig:
    bucket: str


@dataclass(frozen=True)
class S3ObjectId:
    bucket: str
    key: str
    version_id: str
    last_modified: datetime | None = None

    def __post_init__(self) -> None:
        if not self.bucket or not self.key:
            raise ValueError("S3 object identity requires bucket and key")
        if not self.version_id.strip() or self.version_id == "null":
            raise ValueError("S3 object identity requires an immutable version id")


@dataclass(frozen=True)
class BootstrapCheck:
    key: str
    required: bool
    available: bool
    object_id: S3ObjectId | None
    message: str


@dataclass(frozen=True)
class BootstrapResult:
    metadata_ready: bool
    worker_start_allowed: bool
    checks: tuple[BootstrapCheck, ...]


class RunState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    STALE = "stale"


class StaleObjectError(RuntimeError):
    pass


class SourceSnapshotError(RuntimeError):
    def __init__(self, results: Sequence[StageResult], message: str):
        super().__init__(message)
        self.results = tuple(results)


@dataclass(frozen=True)
class StageResult:
    target: str
    stage: str
    outcome: str
    row_count: int | None = None
    error: str | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SqsMessage:
    receipt_handle: str
    body: str


@dataclass(frozen=True)
class MessageResult:
    acknowledged: bool
    states: tuple[RunState, ...]


class S3Adapter(Protocol):
    def head_current(self, bucket: str, key: str) -> S3ObjectId | None: ...

    def read_version(self, object_id: S3ObjectId) -> bytes: ...


class SQSAdapter(Protocol):
    def delete_message(self, receipt_handle: str) -> None: ...


class SNSAdapter(Protocol):
    def publish(self, subject: str, message: str) -> None: ...


class MessageProcessor(Protocol):
    def process(
        self, object_id: S3ObjectId, body: bytes
    ) -> Sequence[StageResult]: ...

    def finalize(self) -> Sequence[StageResult]: ...


class Boto3S3Adapter:
    def __init__(self, client):
        self.client = client

    def head_current(self, bucket: str, key: str) -> S3ObjectId | None:
        from botocore.exceptions import ClientError

        try:
            response = self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return S3ObjectId(
            bucket, key, response.get("VersionId") or "", response.get("LastModified")
        )

    def read_version(self, object_id: S3ObjectId) -> bytes:
        response = self.client.get_object(
            Bucket=object_id.bucket,
            Key=object_id.key,
            VersionId=object_id.version_id,
        )
        return response["Body"].read()


class SourceSnapshotProcessor:
    def __init__(self, engine: Engine, *, s3: S3Adapter):
        self.engine = engine
        self.s3 = s3

    def process(
        self, object_id: S3ObjectId, body: bytes
    ) -> Sequence[StageResult]:
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as handle:
            path = Path(handle.name)
            handle.write(body)
        try:
            dataset = self._inspect(object_id, path)
        finally:
            path.unlink(missing_ok=True)

        run_id = self._run_id(object_id)
        extraction = extract_source_snapshot(
            dataset,
            engine=self.engine,
            filename=object_id.key,
            bucket=object_id.bucket,
            object_key=object_id.key,
            object_version_id=object_id.version_id,
            ingestion_run_id=run_id,
        )
        result = StageResult(
            target=object_id.key,
            stage="extract",
            outcome="failed" if extraction.errors else "succeeded",
            row_count=extraction.rows_loaded,
            error="; ".join(extraction.errors) or None,
            details={
                "energy_source": dataset.source,
                "raw_table": extraction.loaded_to,
                "object_version_id": object_id.version_id,
                "reused": extraction.skipped,
            },
        )
        results = [result]
        if extraction.errors:
            raise SourceSnapshotError(
                results, f"extract failed: {'; '.join(extraction.errors)}"
            )
        raw_table = extraction.loaded_to
        if raw_table is None:
            raise SourceSnapshotError(results, "extract produced no raw version")

        transform = transform_source_snapshot(
            dataset.source,
            raw_table,
            engine=self.engine,
            ingestion_run_id=run_id,
        )
        results.append(
            StageResult(
                target=dataset.source,
                stage="transform",
                outcome="failed" if transform.errors else "succeeded",
                row_count=transform.rows_written,
                error="; ".join(transform.errors) or None,
                details={
                    "raw_table": raw_table,
                    "bad_quality": transform.bad_quality,
                    "synthetic_ids": transform.synthetic_ids,
                },
            )
        )
        if transform.errors:
            raise SourceSnapshotError(
                results, f"transform failed: {'; '.join(transform.errors)}"
            )

        load = load_source_snapshot(
            dataset.source,
            engine=self.engine,
            ingestion_run_id=run_id,
        )
        results.append(
            StageResult(
                target=load.target,
                stage="load",
                outcome="failed" if load.errors else "succeeded",
                row_count=load.rows_inserted + load.rows_updated,
                error="; ".join(load.errors) or None,
                details={
                    "inserted": load.rows_inserted,
                    "updated": load.rows_updated,
                    "retained": load.rows_retained,
                    "collisions": load.collisions,
                },
            )
        )
        if load.errors:
            raise SourceSnapshotError(
                results, f"load failed: {'; '.join(load.errors)}"
            )

        return tuple(results)

    def finalize(self) -> Sequence[StageResult]:
        ensure_core_tables(self.engine)
        marts = build_marts(self.engine)
        result = StageResult(
            target="marts",
            stage="marts",
            outcome="failed" if marts.errors else "succeeded",
            row_count=len(marts.refreshed),
            error="; ".join(marts.errors) or None,
            details={
                "refreshed": marts.refreshed,
                "created": marts.created,
                "verified": marts.verified,
            },
        )
        if marts.errors:
            raise SourceSnapshotError(
                (result,), f"marts failed: {'; '.join(marts.errors)}"
            )
        return (result,)

    def _inspect(self, object_id: S3ObjectId, path: Path) -> SourceDataset:
        """Validate the GPKG, reporting a rejection as a failed extract stage.

        A rejected snapshot is a deterministic input error, so it gets a stage
        result like any other stage outcome rather than surfacing as an
        unexplained exception.
        """
        try:
            return inspect_source_gpkg(path)
        except SourceValidationError as error:
            raise SourceSnapshotError(
                (
                    StageResult(
                        target=object_id.key,
                        stage="extract",
                        outcome="failed",
                        error=str(error),
                    ),
                ),
                f"extract failed: {error}",
            ) from error

    def _run_id(self, object_id: S3ObjectId) -> str:
        with self.engine.connect() as connection:
            run_id = connection.execute(
                text(
                    f"SELECT run_id FROM {SERVICE_SCHEMA}.ingestion_runs "
                    "WHERE bucket = :bucket AND object_key = :object_key "
                    "AND object_version_id = :object_version_id"
                ),
                {
                    "bucket": object_id.bucket,
                    "object_key": object_id.key,
                    "object_version_id": object_id.version_id,
                },
            ).scalar()
        if run_id is None:
            raise RuntimeError("No ingestion run for object version")
        return str(run_id)


def _ensure_service_metadata(engine: Engine) -> None:
    _ensure_schema(engine, SERVICE_SCHEMA)
    _create_log_table(engine, SERVICE_SCHEMA)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {SERVICE_SCHEMA}.ingestion_runs (
                    run_id UUID PRIMARY KEY,
                    bucket TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    object_version_id TEXT NOT NULL,
                    input_kind TEXT,
                    object_last_modified TIMESTAMPTZ,
                    state TEXT NOT NULL,
                    current_stage TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    terminal_error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ,
                    UNIQUE (bucket, object_key, object_version_id)
                )
                """
            )
        )
        connection.execute(
            text(
                f"ALTER TABLE {SERVICE_SCHEMA}.ingestion_runs "
                "ADD COLUMN IF NOT EXISTS input_kind TEXT"
            )
        )
        connection.execute(
            text(
                f"ALTER TABLE {SERVICE_SCHEMA}.ingestion_runs "
                "ADD COLUMN IF NOT EXISTS object_last_modified TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {SERVICE_SCHEMA}.stage_results (
                    stage_result_id BIGSERIAL PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES {SERVICE_SCHEMA}.ingestion_runs(run_id),
                    attempt INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    row_count BIGINT,
                    error TEXT,
                    details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMPTZ,
                    UNIQUE (run_id, attempt, target, stage)
                )
                """
            )
        )
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {SERVICE_SCHEMA}.source_memberships (
                    run_id UUID NOT NULL REFERENCES {SERVICE_SCHEMA}.ingestion_runs(run_id),
                    energy_source TEXT NOT NULL,
                    unit_key TEXT NOT NULL,
                    reference_id TEXT,
                    bad_quality BOOLEAN NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, unit_key)
                )
                """
            )
        )


def bootstrap(
    config: BootstrapConfig,
    *,
    engine: Engine,
    s3: S3Adapter,
) -> BootstrapResult:
    _ensure_service_metadata(engine)
    checks = []
    for required, keys in ((True, BOUNDARY_KEYS), (False, SOURCE_KEYS)):
        for key in keys:
            object_id = s3.head_current(config.bucket, key)
            checks.append(
                BootstrapCheck(
                    key=key,
                    required=required,
                    available=object_id is not None,
                    object_id=object_id,
                    message="available" if object_id is not None else "missing",
                )
            )
    return BootstrapResult(
        metadata_ready=True,
        worker_start_allowed=all(
            check.available for check in checks if check.required
        ),
        checks=tuple(checks),
    )


@dataclass(frozen=True)
class MessageObjects:
    """The accepted objects of a message and whether it is safe to delete it.

    A record for an unaccepted key is settled work: it is deliberately ignored,
    so the message can be deleted. A record that cannot be read as an S3
    identity is *not* settled — nothing has claimed it, and acknowledging would
    drop it without a run, so such a message is left for redelivery until the
    deterministic-failure path (issue #36, stories 28-29) can announce it.
    """

    object_ids: tuple[S3ObjectId, ...] = ()
    acknowledgable: bool = False


def _object_ids(message: SqsMessage) -> MessageObjects:
    try:
        records = json.loads(message.body)["Records"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return MessageObjects()
    object_ids = []
    malformed = False
    for record in records:
        try:
            s3_record = record["s3"]
            object_id = S3ObjectId(
                bucket=s3_record["bucket"]["name"],
                key=unquote_plus(s3_record["object"]["key"]),
                version_id=s3_record["object"]["versionId"],
            )
        except (KeyError, TypeError, ValueError):
            log.warning("Ignoring unreadable S3 record in message: %r", record)
            malformed = True
            continue
        if object_id.key not in ACCEPTED_KEYS:
            log.info("Ignoring event for unaccepted key %s", object_id.key)
            continue
        object_ids.append(object_id)
    return MessageObjects(tuple(object_ids), not malformed)


def _input_kind(object_id: S3ObjectId) -> str:
    return "boundary" if object_id.key in BOUNDARY_KEYS else "source"


def _resolve_current(engine: Engine, s3: S3Adapter, event: S3ObjectId) -> S3ObjectId:
    """Return the announced version stamped with the timestamp S3 serves it.

    The version check rejects an event S3 has already superseded. The age check
    then rejects a delayed redelivery of a version whose key has since been
    ingested from a newer upload — reachable when a lifecycle rule has removed
    that newer version, leaving the older one current again. Both need the HEAD
    timestamp, because an SQS event carries no `LastModified`, and the run row
    has to be stamped before the run starts.
    """
    current = s3.head_current(event.bucket, event.key)
    if current is None or current.version_id != event.version_id:
        raise StaleObjectError(
            f"Superseded object version: {event.key} {event.version_id}"
        )
    resolved = S3ObjectId(
        event.bucket,
        event.key,
        event.version_id,
        current.last_modified or event.last_modified,
    )
    newer = _newer_succeeded_run(engine, resolved)
    if newer is not None:
        raise StaleObjectError(
            f"Delayed object version {event.version_id} of {event.key} "
            f"is older than already-loaded {newer}"
        )
    return resolved


def _stamp_last_modified(
    engine: Engine, run_id: uuid.UUID, last_modified: datetime | None
) -> None:
    """Record the served timestamp of the version this run is processing.

    The run row is created from the SQS event, which carries no `LastModified`,
    so the HEAD result is written here. A superseded version has no timestamp to
    record and keeps a null column rather than a guessed one.
    """
    if last_modified is None:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET object_last_modified = :last_modified "
                "WHERE run_id = :run_id"
            ),
            {"last_modified": last_modified, "run_id": str(run_id)},
        )


def _newer_succeeded_run(engine: Engine, object_id: S3ObjectId) -> str | None:
    """Return the version id of a newer already-succeeded run for this key."""
    if object_id.last_modified is None:
        return None
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT object_version_id FROM {SERVICE_SCHEMA}.ingestion_runs "
                "WHERE bucket = :bucket AND object_key = :object_key "
                "AND state = :state "
                "AND object_last_modified > :last_modified "
                "ORDER BY object_last_modified DESC LIMIT 1"
            ),
            {
                "bucket": object_id.bucket,
                "object_key": object_id.key,
                "state": RunState.SUCCEEDED.value,
                "last_modified": object_id.last_modified,
            },
        ).scalar()
    return str(row) if row is not None else None


def _start_run(engine: Engine, object_id: S3ObjectId):
    with engine.begin() as connection:
        row = connection.execute(
            text(
                f"SELECT run_id, state, attempt_count "
                f"FROM {SERVICE_SCHEMA}.ingestion_runs "
                "WHERE bucket = :bucket "
                "AND object_key = :object_key "
                "AND object_version_id = :object_version_id"
            ),
            {
                "bucket": object_id.bucket,
                "object_key": object_id.key,
                "object_version_id": object_id.version_id,
            },
        ).mappings().first()
        if row is None:
            run_id = uuid.uuid4()
            attempt = 1
            connection.execute(
                text(
                    f"INSERT INTO {SERVICE_SCHEMA}.ingestion_runs "
                    "(run_id, bucket, object_key, object_version_id, "
                    "input_kind, object_last_modified, state) "
                    "VALUES (:run_id, :bucket, :object_key, :object_version_id, "
                    ":input_kind, :object_last_modified, :state)"
                ),
                {
                    "run_id": str(run_id),
                    "bucket": object_id.bucket,
                    "object_key": object_id.key,
                    "object_version_id": object_id.version_id,
                    "input_kind": _input_kind(object_id),
                    "object_last_modified": object_id.last_modified,
                    "state": RunState.PENDING.value,
                },
            )
        else:
            run_id = row["run_id"]
            existing_state = RunState(row["state"])
            if existing_state in {
                RunState.SUCCEEDED,
                RunState.TERMINAL,
                RunState.STALE,
            }:
                return run_id, row["attempt_count"], existing_state
            attempt = row["attempt_count"] + 1
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET input_kind = :input_kind, "
                "object_last_modified = COALESCE(:object_last_modified, "
                "object_last_modified), "
                "state = :state, "
                "current_stage = :current_stage, "
                "attempt_count = :attempt, started_at = CURRENT_TIMESTAMP, "
                "finished_at = NULL, terminal_error = NULL "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": str(run_id),
                "input_kind": _input_kind(object_id),
                "object_last_modified": object_id.last_modified,
                "state": RunState.RUNNING.value,
                "current_stage": "processing",
                "attempt": attempt,
            },
        )
    return run_id, attempt, RunState.RUNNING


def _record_success(
    engine: Engine,
    run_id: uuid.UUID,
    attempt: int,
    results: Sequence[StageResult],
) -> None:
    _record_stage_results(engine, run_id, attempt, results)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET state = :state, current_stage = 'complete', "
                "finished_at = CURRENT_TIMESTAMP "
                "WHERE run_id = :run_id"
            ),
            {"run_id": str(run_id), "state": RunState.SUCCEEDED.value},
        )


def _record_stage_results(
    engine: Engine,
    run_id: uuid.UUID,
    attempt: int,
    results: Sequence[StageResult],
) -> None:
    with engine.begin() as connection:
        for result in results:
            connection.execute(
                text(
                    f"INSERT INTO {SERVICE_SCHEMA}.stage_results "
                    "(run_id, attempt, target, stage, outcome, row_count, error, "
                    "details, finished_at) "
                    "VALUES (:run_id, :attempt, :target, :stage, :outcome, "
                    ":row_count, :error, CAST(:details AS jsonb), CURRENT_TIMESTAMP)"
                ),
                {
                    "run_id": str(run_id),
                    "attempt": attempt,
                    "target": result.target,
                    "stage": result.stage,
                    "outcome": result.outcome,
                    "row_count": result.row_count,
                    "error": result.error,
                    "details": json.dumps(result.details),
                },
            )


def _record_retryable(
    engine: Engine,
    run_id: uuid.UUID,
    error: Exception,
    stage: str = "processing",
) -> None:
    _record_failure(engine, run_id, RunState.RETRYABLE, error, stage)


def _record_stale(
    engine: Engine,
    run_id: uuid.UUID,
    error: Exception,
) -> None:
    _record_failure(engine, run_id, RunState.STALE, error, "version-check")


def _record_failure(
    engine: Engine,
    run_id: uuid.UUID,
    state: RunState,
    error: Exception,
    stage: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET state = :state, current_stage = :stage, "
                "terminal_error = :error, finished_at = CURRENT_TIMESTAMP "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": str(run_id),
                "state": state.value,
                "stage": stage,
                "error": str(error),
            },
        )


def _failing_stage(error: SourceSnapshotError) -> str:
    for result in reversed(error.results):
        if result.outcome == "failed":
            return result.stage
    return "processing"


def process_one_message(
    message: SqsMessage,
    *,
    engine: Engine,
    s3: S3Adapter,
    sqs: SQSAdapter,
    sns: SNSAdapter,
    processor: MessageProcessor,
) -> MessageResult:
    states = []
    successes: list[tuple[uuid.UUID, int, list[StageResult], int]] = []
    parsed = _object_ids(message)
    for event in parsed.object_ids:
        run_id, attempt, state = _start_run(engine, event)
        if state in {RunState.SUCCEEDED, RunState.TERMINAL, RunState.STALE}:
            states.append(state)
            continue
        try:
            object_id = _resolve_current(engine, s3, event)
        except StaleObjectError as error:
            _record_stale(engine, run_id, error)
            states.append(RunState.STALE)
            continue
        _stamp_last_modified(engine, run_id, object_id.last_modified)
        try:
            body = s3.read_version(object_id)
            results = list(processor.process(object_id, body))
            successes.append((run_id, attempt, results, len(states)))
            states.append(RunState.SUCCEEDED)
        except SourceSnapshotError as error:
            _record_stage_results(engine, run_id, attempt, error.results)
            _record_retryable(engine, run_id, error, _failing_stage(error))
            states.append(RunState.RETRYABLE)
        except Exception as error:
            _record_retryable(engine, run_id, error)
            states.append(RunState.RETRYABLE)

    if successes:
        try:
            marts_results = list(processor.finalize())
        except SourceSnapshotError as error:
            # Marts are shared by the whole message, so a refresh failure leaves
            # no record in it complete: every successful source run in the
            # message is downgraded to retryable and carries the marts failure,
            # rather than only the last one being marked incomplete.
            for run_id, attempt, results, index in successes:
                _record_stage_results(
                    engine, run_id, attempt, (*results, *error.results)
                )
                _record_retryable(engine, run_id, error, _failing_stage(error))
                states[index] = RunState.RETRYABLE
        else:
            for run_id, attempt, results, _ in successes:
                _record_success(
                    engine, run_id, attempt, (*results, *marts_results)
                )

    acknowledged = parsed.acknowledgable and all(
        state in {RunState.SUCCEEDED, RunState.TERMINAL, RunState.STALE}
        for state in states
    )
    if acknowledged:
        sqs.delete_message(message.receipt_handle)
    return MessageResult(acknowledged=acknowledged, states=tuple(states))
