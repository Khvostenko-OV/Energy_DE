from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from urllib.parse import unquote_plus

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import SERVICE_SCHEMA, SOURCE_NAMES
from etl.db_utils import _create_log_table, _ensure_schema


BOUNDARY_KEYS = tuple(f"boundaries/level-{level}.gpkg" for level in range(4))
SOURCE_KEYS = tuple(f"sources/{source}.gpkg" for source in SOURCE_NAMES)


@dataclass(frozen=True)
class BootstrapConfig:
    bucket: str


@dataclass(frozen=True)
class S3ObjectId:
    bucket: str
    key: str
    version_id: str

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
        return S3ObjectId(bucket, key, response.get("VersionId") or "")

    def read_version(self, object_id: S3ObjectId) -> bytes:
        response = self.client.get_object(
            Bucket=object_id.bucket,
            Key=object_id.key,
            VersionId=object_id.version_id,
        )
        return response["Body"].read()


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


def _object_ids(message: SqsMessage) -> tuple[S3ObjectId, ...]:
    try:
        records = json.loads(message.body)["Records"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return ()
    object_ids = []
    for record in records:
        try:
            s3_record = record["s3"]
            object_id = S3ObjectId(
                bucket=s3_record["bucket"]["name"],
                key=unquote_plus(s3_record["object"]["key"]),
                version_id=s3_record["object"]["versionId"],
            )
        except (KeyError, TypeError, ValueError):
            continue
        object_ids.append(object_id)
    return tuple(object_ids)


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
                    "(run_id, bucket, object_key, object_version_id, state) "
                    "VALUES (:run_id, :bucket, :object_key, :object_version_id, :state)"
                ),
                {
                    "run_id": str(run_id),
                    "bucket": object_id.bucket,
                    "object_key": object_id.key,
                    "object_version_id": object_id.version_id,
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
                "SET state = :state, current_stage = :current_stage, "
                "attempt_count = :attempt, started_at = CURRENT_TIMESTAMP, "
                "finished_at = NULL, terminal_error = NULL "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": str(run_id),
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
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET state = :state, current_stage = 'complete', "
                "finished_at = CURRENT_TIMESTAMP "
                "WHERE run_id = :run_id"
            ),
            {"run_id": str(run_id), "state": RunState.SUCCEEDED.value},
        )


def _record_retryable(
    engine: Engine,
    run_id: uuid.UUID,
    error: Exception,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.ingestion_runs "
                "SET state = :state, current_stage = 'processing', "
                "terminal_error = :error, finished_at = CURRENT_TIMESTAMP "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": str(run_id),
                "state": RunState.RETRYABLE.value,
                "error": str(error),
            },
        )


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
    for object_id in _object_ids(message):
        run_id, attempt, state = _start_run(engine, object_id)
        if state in {RunState.SUCCEEDED, RunState.TERMINAL, RunState.STALE}:
            states.append(state)
            continue
        try:
            body = s3.read_version(object_id)
            results = processor.process(object_id, body)
            _record_success(engine, run_id, attempt, results)
            states.append(RunState.SUCCEEDED)
        except Exception as error:
            _record_retryable(engine, run_id, error)
            states.append(RunState.RETRYABLE)
    acknowledged = bool(states) and all(
        state in {RunState.SUCCEEDED, RunState.TERMINAL, RunState.STALE}
        for state in states
    )
    if acknowledged:
        sqs.delete_message(message.receipt_handle)
    return MessageResult(acknowledged=acknowledged, states=tuple(states))
