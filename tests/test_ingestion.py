import json
import os
import uuid

from click.testing import CliRunner
import pytest
from sqlalchemy import create_engine, text

from etl import ingestion
import etl.__main__ as cli_module
from etl.__main__ import cli


ENGINE = create_engine(os.environ["DATABASE_URL"])


def test_ingestion_identity_requires_immutable_s3_version():
    with pytest.raises(ValueError, match="immutable version id"):
        ingestion.S3ObjectId("energy-data", "sources/solar.gpkg", "null")


class FakeS3:
    def __init__(self, *missing_keys: str):
        self.missing_keys = set(missing_keys)
        self.reads = []

    def head_current(self, bucket: str, key: str):
        if key in self.missing_keys:
            return None
        if key.startswith("boundaries/") or key.startswith("sources/"):
            return ingestion.S3ObjectId(bucket, key, "version-1")
        return None

    def read_version(self, object_id: ingestion.S3ObjectId) -> bytes:
        self.reads.append(object_id)
        return b"version-42-content"


class FakeSQS:
    def __init__(self):
        self.deleted = []

    def delete_message(self, receipt_handle: str) -> None:
        self.deleted.append(receipt_handle)


class FakeSNS:
    def __init__(self):
        self.messages = []

    def publish(self, subject: str, message: str) -> None:
        self.messages.append((subject, message))


class FakeProcessor:
    def __init__(self):
        self.objects = []

    def process(self, object_id, body: bytes):
        assert body == b"version-42-content"
        self.objects.append(object_id)
        return (
            ingestion.StageResult(
                target=object_id.key,
                stage="extract",
                outcome="succeeded",
                row_count=1,
            ),
        )


def test_bootstrap_prepares_service_metadata_for_all_boundary_levels(monkeypatch):
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)

    try:
        result = ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=FakeS3(),
        )

        assert result.metadata_ready
        assert result.worker_start_allowed
        assert [check.key for check in result.checks if check.required] == [
            "boundaries/level-0.gpkg",
            "boundaries/level-1.gpkg",
            "boundaries/level-2.gpkg",
            "boundaries/level-3.gpkg",
        ]
        with ENGINE.connect() as connection:
            tables = {
                row.name
                for row in connection.execute(
                    text(
                        "SELECT table_name AS name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            }
        assert {
            "ingestion_runs",
            "loaded_files",
            "source_memberships",
            "stage_results",
        } <= tables
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_worker_processes_exact_object_version_and_acknowledges_message(monkeypatch):
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)
    s3 = FakeS3()
    sqs = FakeSQS()
    sns = FakeSNS()
    processor = FakeProcessor()

    try:
        ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=s3,
        )
        message = ingestion.SqsMessage(
            receipt_handle="receipt-1",
            body=json.dumps(
                {
                    "Records": [
                        {
                            "eventSource": "aws:s3",
                            "s3": {
                                "bucket": {"name": "energy-data"},
                                "object": {
                                    "key": "sources/solar.gpkg",
                                    "versionId": "version-42",
                                },
                            },
                        }
                    ]
                }
            ),
        )

        result = ingestion.process_one_message(
            message,
            engine=ENGINE,
            s3=s3,
            sqs=sqs,
            sns=sns,
            processor=processor,
        )

        assert {state.value for state in ingestion.RunState} == {
            "pending",
            "running",
            "succeeded",
            "retryable",
            "terminal",
            "stale",
        }
        assert result.acknowledged
        assert sqs.deleted == ["receipt-1"]
        expected_object = ingestion.S3ObjectId(
            "energy-data", "sources/solar.gpkg", "version-42"
        )
        assert s3.reads == [expected_object]
        assert processor.objects == [expected_object]
        with ENGINE.connect() as connection:
            run = connection.execute(
                text(
                    f"SELECT bucket, object_key, object_version_id, state "
                    f"FROM {schema}.ingestion_runs"
                )
            ).mappings().one()
            stage = connection.execute(
                text(
                    f"SELECT target, stage, outcome, row_count "
                    f"FROM {schema}.stage_results"
                )
            ).mappings().one()
        assert dict(run) == {
            "bucket": "energy-data",
            "object_key": "sources/solar.gpkg",
            "object_version_id": "version-42",
            "state": "succeeded",
        }
        assert dict(stage) == {
            "target": "sources/solar.gpkg",
            "stage": "extract",
            "outcome": "succeeded",
            "row_count": 1,
        }
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_bootstrap_blocks_worker_for_missing_boundary_but_not_missing_source(monkeypatch):
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)

    try:
        source_missing = ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=FakeS3("sources/bio.gpkg"),
        )
        boundary_missing = ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=FakeS3("boundaries/level-2.gpkg"),
        )

        assert source_missing.worker_start_allowed
        assert next(
            check
            for check in source_missing.checks
            if check.key == "sources/bio.gpkg"
        ).message == "missing"
        assert not boundary_missing.worker_start_allowed
        assert next(
            check
            for check in boundary_missing.checks
            if check.key == "boundaries/level-2.gpkg"
        ).message == "missing"
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_bootstrap_command_reports_fatal_boundary_result(monkeypatch):
    result = ingestion.BootstrapResult(
        metadata_ready=True,
        worker_start_allowed=False,
        checks=(
            ingestion.BootstrapCheck(
                key="boundaries/level-0.gpkg",
                required=True,
                available=False,
                object_id=None,
                message="missing",
            ),
        ),
    )
    monkeypatch.setattr("etl.__main__.get_engine", lambda: object())
    monkeypatch.setattr("etl.__main__._s3_adapter", lambda: object(), raising=False)
    monkeypatch.setattr(
        "etl.__main__.bootstrap_ingestion",
        lambda config, *, engine, s3: result,
        raising=False,
    )

    invocation = CliRunner().invoke(cli, ["bootstrap", "--bucket", "energy-data"])

    assert invocation.exit_code == 1
    assert "Metadata ready   : yes" in invocation.output
    assert "Worker start     : blocked" in invocation.output
    assert "boundaries/level-0.gpkg (required): missing" in invocation.output


def test_cli_keeps_local_stage_commands_and_run_all():
    invocation = CliRunner().invoke(cli, ["--help"])

    assert invocation.exit_code == 0
    for command in (
        "boundaries",
        "extract",
        "transform",
        "load",
        "marts",
        "run-all",
        "bootstrap",
    ):
        assert command in invocation.output


def test_run_all_keeps_existing_stage_order(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_module, "boundaries", lambda force: calls.append("boundaries"))
    monkeypatch.setattr(cli_module, "extract", lambda force: calls.append("extract"))
    monkeypatch.setattr(cli_module, "transform", lambda: calls.append("transform"))
    monkeypatch.setattr(cli_module, "load", lambda: calls.append("load"))
    monkeypatch.setattr(cli_module, "marts", lambda: calls.append("marts"))

    invocation = CliRunner().invoke(cli, ["run-all"])

    assert invocation.exit_code == 0
    assert calls == ["boundaries", "extract", "transform", "load", "marts"]
