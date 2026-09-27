import json
import os
import uuid
from datetime import datetime, timezone

import geopandas as gpd
import pandas
from click.testing import CliRunner
import pytest
from shapely.geometry import Point, box
from sqlalchemy import create_engine, text

from etl import db_utils, extract, ingestion, load, marts, transform, utils, verify
import etl.__main__ as cli_module
from etl.__main__ import cli


ENGINE = create_engine(os.environ["DATABASE_URL"])


def test_ingestion_identity_requires_immutable_s3_version():
    with pytest.raises(ValueError, match="immutable version id"):
        ingestion.S3ObjectId("energy-data", "sources/solar.gpkg", "null")


class FakeS3:
    def __init__(self, *missing_keys: str, current_version: str = "version-1"):
        self.missing_keys = set(missing_keys)
        self.current_version = current_version
        self.reads = []
        self.bodies = {}

    def head_current(self, bucket: str, key: str):
        if key in self.missing_keys:
            return None
        if key.startswith("boundaries/") or key.startswith("sources/"):
            return ingestion.S3ObjectId(bucket, key, self.current_version)
        return None

    def read_version(self, object_id: ingestion.S3ObjectId) -> bytes:
        self.reads.append(object_id)
        return self.bodies.get(object_id.key, b"version-42-content")


class VersionedS3:
    def __init__(self):
        self.current = {}
        self.objects = {}
        self.last_modified = {}
        self.reads = []

    def put(self, key: str, version_id: str, body: bytes) -> None:
        self.current[key] = version_id
        self.objects[version_id] = body

    def head_current(self, bucket: str, key: str):
        version_id = self.current.get(key)
        if version_id is None:
            return None
        return ingestion.S3ObjectId(
            bucket, key, version_id, self.last_modified.get(version_id)
        )

    def read_version(self, object_id: ingestion.S3ObjectId) -> bytes:
        self.reads.append(object_id)
        return self.objects[object_id.version_id]


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
        self.finalized = 0

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

    def finalize(self):
        self.finalized += 1
        return (
            ingestion.StageResult(
                target="marts",
                stage="marts",
                outcome="succeeded",
                row_count=2,
            ),
        )


class FailingProcessor:
    def __init__(self):
        self.finalized = 0

    def process(self, object_id, body: bytes):
        results = (
            ingestion.StageResult(
                target=object_id.key,
                stage="extract",
                outcome="succeeded",
                row_count=3,
            ),
            ingestion.StageResult(
                target=object_id.key,
                stage="load",
                outcome="failed",
                row_count=0,
                error="load failed: boom",
            ),
        )
        raise ingestion.SourceSnapshotError(results, "load failed: boom")

    def finalize(self):
        self.finalized += 1
        return ()


def _two_record_message(handle: str = "receipt-1") -> ingestion.SqsMessage:
    return ingestion.SqsMessage(
        receipt_handle=handle,
        body=json.dumps(
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": "energy-data"},
                            "object": {
                                "key": "sources/solar.gpkg",
                                "versionId": "version-1",
                            },
                        },
                    },
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": "energy-data"},
                            "object": {
                                "key": "sources/wind.gpkg",
                                "versionId": "version-1",
                            },
                        },
                    },
                ]
            }
        ),
    )


def test_marts_run_once_per_message_not_once_per_object(monkeypatch):
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)
    s3 = FakeS3()
    sqs = FakeSQS()
    processor = FakeProcessor()

    try:
        ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=s3,
        )
        result = ingestion.process_one_message(
            _two_record_message(),
            engine=ENGINE,
            s3=s3,
            sqs=sqs,
            sns=FakeSNS(),
            processor=processor,
        )

        assert result.acknowledged
        assert [state.value for state in result.states] == [
            "succeeded",
            "succeeded",
        ]
        assert len(processor.objects) == 2
        # One refresh for the message...
        assert processor.finalized == 1
        with ENGINE.connect() as connection:
            marts_rows = connection.execute(
                text(
                    f"SELECT run_id, stage FROM {schema}.stage_results "
                    "WHERE stage = 'marts'"
                )
            ).all()
            runs = connection.execute(
                text(f"SELECT state FROM {schema}.ingestion_runs ORDER BY created_at")
            ).scalars().all()
        # ...recorded against every run that took part in it, so no run claims
        # completion without the marts step it shared.
        assert len(marts_rows) == 2
        assert len({row[0] for row in marts_rows}) == 2
        assert runs == ["succeeded", "succeeded"]
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_partial_stage_results_survive_a_failed_object(monkeypatch):
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)
    s3 = FakeS3()
    sqs = FakeSQS()
    processor = FailingProcessor()

    try:
        ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=s3,
        )
        message = ingestion.SqsMessage(
            receipt_handle="receipt-2",
            body=json.dumps(
                {
                    "Records": [
                        {
                            "eventSource": "aws:s3",
                            "s3": {
                                "bucket": {"name": "energy-data"},
                                "object": {
                                    "key": "sources/solar.gpkg",
                                    "versionId": "version-1",
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
            sns=FakeSNS(),
            processor=processor,
        )

        assert not result.acknowledged
        assert [state.value for state in result.states] == ["retryable"]
        assert sqs.deleted == []
        assert processor.finalized == 0
        with ENGINE.connect() as connection:
            run = connection.execute(
                text(
                    f"SELECT state, terminal_error FROM {schema}.ingestion_runs"
                )
            ).mappings().one()
            stages = connection.execute(
                text(
                    f"SELECT stage, outcome, error FROM {schema}.stage_results "
                    "ORDER BY stage"
                )
            ).mappings().all()
        assert run["state"] == "retryable"
        assert "load failed" in run["terminal_error"]
        assert [dict(stage) for stage in stages] == [
            {"stage": "extract", "outcome": "succeeded", "error": None},
            {
                "stage": "load",
                "outcome": "failed",
                "error": "load failed: boom",
            },
        ]
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


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
    s3 = FakeS3(current_version="version-42")
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
        assert processor.finalized == 1
        with ENGINE.connect() as connection:
            run = connection.execute(
                text(
                    f"SELECT bucket, object_key, object_version_id, input_kind, state "
                    f"FROM {schema}.ingestion_runs"
                )
            ).mappings().one()
            stages = connection.execute(
                text(
                    f"SELECT target, stage, outcome, row_count "
                    f"FROM {schema}.stage_results ORDER BY stage"
                )
            ).mappings().all()
        assert dict(run) == {
            "bucket": "energy-data",
            "object_key": "sources/solar.gpkg",
            "object_version_id": "version-42",
            "input_kind": "source",
            "state": "succeeded",
        }
        assert [dict(stage) for stage in stages] == [
            {
                "target": "sources/solar.gpkg",
                "stage": "extract",
                "outcome": "succeeded",
                "row_count": 1,
            },
            {
                "target": "marts",
                "stage": "marts",
                "outcome": "succeeded",
                "row_count": 2,
            },
        ]
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


def _solar_snapshot(rows):
    records = []
    for row in rows:
        coordinates = row.get("coordinates", (10.0, 50.0))
        records.append(
            {
                "energy_source": row.get("energy_source", "Solar Energy"),
                "installed_capacity": row.get("installed_capacity", 100.0),
                "commissioning_date": row.get("commissioning_date", "2020-01-01"),
                "decommissioning_date": row.get("decommissioning_date"),
                "solar_type": row.get("solar_type", "Utility"),
                "area_id": None,
                "alignment": None,
                "inclination": None,
                "location": row.get("location", "Agrivoltaics"),
                "x_coordinates": coordinates[0],
                "y_coordinates": coordinates[1],
                "geo_accuracy": row.get("geo_accuracy", 1),
                "note": None,
                "reference_source": "test",
                "reference_id": row.get("reference_id"),
                "reference_date": pandas.Timestamp(row.get("reference_date", "2024-01-01")),
                "geometry": Point(*coordinates),
            }
        )
    return gpd.GeoDataFrame(records, crs="EPSG:4326")


def _write_source_snapshot(tmp_path, name, rows):
    path = tmp_path / name
    _solar_snapshot(rows).to_file(path, layer="content_layer", driver="GPKG")
    return path.read_bytes()


def _source_message(version_id, source="solar"):
    return ingestion.SqsMessage(
        receipt_handle=f"receipt-{version_id}",
        body=json.dumps(
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": "energy-data"},
                            "object": {
                                "key": f"sources/{source}.gpkg",
                                "versionId": version_id,
                            },
                        },
                    }
                ]
            }
        ),
    )


def _decomposed_properties(engine, core_schema, energy_source, reference_id):
    """The (name, value) whitelist links one core unit keeps after a load."""
    with engine.connect() as connection:
        return {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    f"SELECT p.name, p.value "
                    f"FROM {core_schema}.generators g "
                    f"JOIN {core_schema}.generator_units_properties up "
                    f"ON up.unit_id = g.unit_id "
                    f"JOIN {core_schema}.generator_properties p "
                    f"ON p.prop_id = up.prop_id "
                    f"WHERE g.energy_source = :source AND g.reference_id = :ref"
                ),
                {"source": energy_source, "ref": reference_id},
            )
        }


@pytest.fixture
def source_pipeline(tmp_path, monkeypatch):
    suffix = uuid.uuid4().hex
    schemas = {
        "raw": f"raw_test_{suffix}",
        "stage": f"stage_test_{suffix}",
        "core": f"core_test_{suffix}",
        "service": f"service_test_{suffix}",
        "marts": f"marts_test_{suffix}",
    }
    module_schemas = {
        ingestion: ("SERVICE_SCHEMA",),
        extract: ("RAW_SCHEMA", "SERVICE_SCHEMA"),
        transform: ("RAW_SCHEMA", "STAGING_SCHEMA", "SERVICE_SCHEMA"),
        load: ("STAGING_SCHEMA", "CORE_SCHEMA", "SERVICE_SCHEMA"),
        marts: ("CORE_SCHEMA", "MARTS_SCHEMA"),
        verify: (
            "RAW_SCHEMA",
            "STAGING_SCHEMA",
            "CORE_SCHEMA",
            "SERVICE_SCHEMA",
            "MARTS_SCHEMA",
        ),
        db_utils: ("RAW_SCHEMA", "STAGING_SCHEMA", "CORE_SCHEMA", "SERVICE_SCHEMA"),
        utils: ("RAW_SCHEMA", "SERVICE_SCHEMA"),
    }
    for module, names in module_schemas.items():
        for name in names:
            key = name.removesuffix("_SCHEMA").lower().replace("staging", "stage")
            monkeypatch.setattr(module, name, schemas[key])

    s3 = VersionedS3()
    for key in ingestion.BOUNDARY_KEYS + ingestion.SOURCE_KEYS:
        s3.current[key] = "bootstrap"
        s3.objects["bootstrap"] = b""
    ingestion.bootstrap(
        ingestion.BootstrapConfig(bucket="energy-data"),
        engine=ENGINE,
        s3=s3,
    )

    boundaries = gpd.GeoDataFrame(
        {
            "country_iso": ["DEU", "DEU", "DEU"],
            "name": ["Test State", "Test Region", "Test District"],
            "level": [1, 2, 3],
            "area": [1.0, 1.0, 1.0],
            "geometry": [box(9.0, 49.0, 11.0, 51.0)] * 3,
        },
        crs="EPSG:4326",
    )
    boundaries.to_postgis(
        "boundaries",
        ENGINE,
        schema=schemas["service"],
        if_exists="replace",
        index=False,
    )
    yield {
        "engine": ENGINE,
        "schemas": schemas,
        "s3": s3,
        "sqs": FakeSQS(),
        "processor": ingestion.SourceSnapshotProcessor(ENGINE, s3=s3),
    }
    with ENGINE.begin() as connection:
        for schema in reversed(tuple(schemas.values())):
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def _write_storage_snapshot(tmp_path, name, rows):
    records = []
    for row in rows:
        coordinates = row.get("coordinates", (12.0, 52.0))
        records.append(
            {
                "energy_source": "Energy Storage",
                "storage_type": row.get("storage_type", "Battery"),
                "storage_capacity": row.get("storage_capacity", 5.0),
                "installed_capacity": row.get("storage_capacity", 5.0),
                "commissioning_date": "2021-01-01",
                "decommissioning_date": None,
                "location": row.get("location", "Grid"),
                "x_coordinates": coordinates[0],
                "y_coordinates": coordinates[1],
                "geo_accuracy": 1,
                "note": None,
                "reference_source": "test",
                "reference_id": row.get("reference_id"),
                "reference_date": pandas.Timestamp(row.get("reference_date", "2024-01-01")),
                "geometry": Point(*coordinates),
            }
        )
    path = tmp_path / name
    gpd.GeoDataFrame(records, crs="EPSG:4326").to_file(
        path, layer="storage_layer", driver="GPKG"
    )
    return path.read_bytes()


def _storage_message(version_id, key="sources/storage.gpkg"):
    return ingestion.SqsMessage(
        receipt_handle=f"receipt-{version_id}",
        body=json.dumps(
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": "energy-data"},
                            "object": {"key": key, "versionId": version_id},
                        },
                    }
                ]
            }
        ),
    )


def test_worker_loads_a_storage_snapshot_into_the_storage_kind(source_pipeline, tmp_path):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    body = _write_storage_snapshot(
        tmp_path,
        "storage-1.gpkg",
        [
            {"reference_id": "bess-1", "storage_capacity": 4.0},
            {"reference_id": None, "storage_capacity": 9.0, "coordinates": (12.5, 52.5)},
        ],
    )

    s3.put("sources/storage.gpkg", "storage-1", body)
    result = ingestion.process_one_message(
        _storage_message("storage-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert result.acknowledged
    with ENGINE.connect() as connection:
        storages = connection.execute(
            text(
                f"SELECT reference_id, storage_type, storage_capacity "
                f"FROM {schemas['core']}.storages ORDER BY unit_id"
            )
        ).mappings().all()
        run = connection.execute(
            text(
                f"SELECT input_kind, state FROM {schemas['service']}.ingestion_runs"
            )
        ).mappings().one()
        stages = {
            row["stage"]
            for row in connection.execute(
                text(
                    f"SELECT stage FROM {schemas['service']}.stage_results"
                )
            ).mappings()
        }
    assert [row["storage_type"] for row in storages] == ["Battery", "Battery"]
    assert [row["storage_capacity"] for row in storages] == [4.0, 9.0]
    assert [row["reference_id"] for row in storages][0] == "bess-1"
    assert [row["reference_id"] for row in storages][1] is None
    assert dict(run) == {"input_kind": "source", "state": "succeeded"}
    assert stages == {"extract", "transform", "load", "marts"}


def _write_mixed_source_snapshot(tmp_path, name):
    """A GPKG whose single layer claims two different Energy sources."""
    mixed = gpd.GeoDataFrame(
        [
            {
                "energy_source": label,
                "installed_capacity": 100.0,
                "commissioning_date": "2020-01-01",
                "decommissioning_date": None,
                "solar_type": "Utility",
                "area_id": None,
                "alignment": None,
                "inclination": None,
                "location": "Roof",
                "x_coordinates": 10.0,
                "y_coordinates": 50.0,
                "geo_accuracy": 1,
                "note": None,
                "reference_source": "test",
                "reference_id": "mixed",
                "reference_date": pandas.Timestamp("2024-01-01"),
                "geometry": Point(10.0, 50.0),
            }
            for label in ("Solar Energy", "Wind Energy")
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / name
    mixed.to_file(path, layer="mixed_layer", driver="GPKG")
    return path.read_bytes()


def test_worker_rejects_an_invalid_snapshot_without_touching_the_database(
    source_pipeline, tmp_path
):
    initial = _write_source_snapshot(
        tmp_path,
        "good.gpkg",
        [{"reference_id": "keep", "installed_capacity": 100.0}],
    )
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]

    s3.put("sources/solar.gpkg", "good-1", initial)
    first = ingestion.process_one_message(
        _source_message("good-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert first.acknowledged

    s3.put("sources/solar.gpkg", "bad-1", _write_mixed_source_snapshot(tmp_path, "invalid.gpkg"))

    result = ingestion.process_one_message(
        _source_message("bad-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert not result.acknowledged
    assert result.states == (ingestion.RunState.RETRYABLE,)
    assert "receipt-bad-1" not in sqs.deleted
    with ENGINE.connect() as connection:
        core = connection.execute(
            text(
                f"SELECT reference_id, installed_capacity "
                f"FROM {schemas['core']}.generators"
            )
        ).mappings().all()
        raw_tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": schemas["raw"]},
        ).scalars().all()
        bad_run = connection.execute(
            text(
                f"SELECT run_id, state, current_stage "
                f"FROM {schemas['service']}.ingestion_runs "
                "WHERE object_version_id = 'bad-1'"
            )
        ).mappings().one()
        bad_stages = connection.execute(
            text(
                f"SELECT stage, outcome, error FROM {schemas['service']}.stage_results "
                "WHERE run_id = :run_id"
            ),
            {"run_id": str(bad_run["run_id"])},
        ).mappings().all()
    assert [dict(row) for row in core] == [
        {"reference_id": "keep", "installed_capacity": 100.0}
    ]
    assert len(raw_tables) == 1
    assert dict(bad_run)["state"] == "retryable"
    assert dict(bad_run)["current_stage"] == "extract"
    # The rejection is explained by a stage result, not a bare retry.
    assert [row["stage"] for row in bad_stages] == ["extract"]
    assert bad_stages[0]["outcome"] == "failed"
    assert bad_stages[0]["error"] == (
        "Source GPKG requires homogeneous Energy source"
    )


def test_worker_keeps_core_when_a_unit_turns_bad_quality(source_pipeline, tmp_path):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    healthy = _write_source_snapshot(
        tmp_path,
        "healthy.gpkg",
        [
            {"reference_id": "stable", "installed_capacity": 100.0},
            {"reference_id": "degrades", "installed_capacity": 80.0},
        ],
    )
    degraded = _write_source_snapshot(
        tmp_path,
        "degraded.gpkg",
        [
            {"reference_id": "stable", "installed_capacity": 100.0},
            {"reference_id": "degrades", "installed_capacity": None},
        ],
    )

    s3.put("sources/solar.gpkg", "healthy-1", healthy)
    assert ingestion.process_one_message(
        _source_message("healthy-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    ).acknowledged

    s3.put("sources/solar.gpkg", "degraded-1", degraded)
    result = ingestion.process_one_message(
        _source_message("degraded-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert result.acknowledged
    with ENGINE.connect() as connection:
        core = {
            row["reference_id"]: row["installed_capacity"]
            for row in connection.execute(
                text(
                    f"SELECT reference_id, installed_capacity "
                    f"FROM {schemas['core']}.generators"
                )
            ).mappings()
        }
        membership = {
            row["reference_id"]: row["bad_quality"]
            for row in connection.execute(
                text(
                    f"SELECT reference_id, bad_quality "
                    f"FROM {schemas['service']}.source_memberships "
                    "WHERE run_id = (SELECT run_id FROM "
                    f"{schemas['service']}.ingestion_runs "
                    "WHERE object_version_id = 'degraded-1')"
                )
            ).mappings()
        }
    assert core == {"stable": 100.0, "degrades": 80.0}
    assert membership == {"stable": False, "degrades": True}


def test_worker_marks_every_run_retryable_when_shared_marts_fail(monkeypatch):
    """A shared marts failure leaves no run in the message complete."""
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)
    s3 = FakeS3()
    sqs = FakeSQS()
    processor = FakeProcessor()

    class FailingMarts(FakeProcessor):
        def finalize(self):
            self.finalized += 1
            result = ingestion.StageResult(
                target="marts",
                stage="marts",
                outcome="failed",
                error="refresh failed",
            )
            raise ingestion.SourceSnapshotError(
                (result,), "marts failed: refresh failed"
            )

    processor = FailingMarts()
    try:
        ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=s3,
        )
        result = ingestion.process_one_message(
            _two_record_message(),
            engine=ENGINE,
            s3=s3,
            sqs=sqs,
            sns=FakeSNS(),
            processor=processor,
        )

        assert not result.acknowledged
        assert [state.value for state in result.states] == [
            "retryable",
            "retryable",
        ]
        assert processor.finalized == 1
        with ENGINE.connect() as connection:
            runs = connection.execute(
                text(
                    f"SELECT object_key, state, current_stage "
                    f"FROM {schema}.ingestion_runs ORDER BY object_key"
                )
            ).mappings().all()
            marts_per_run = connection.execute(
                text(
                    f"SELECT run_id, outcome FROM {schema}.stage_results "
                    "WHERE stage = 'marts' ORDER BY run_id"
                )
            ).all()
        assert [dict(row) for row in runs] == [
            {
                "object_key": "sources/solar.gpkg",
                "state": "retryable",
                "current_stage": "marts",
            },
            {
                "object_key": "sources/wind.gpkg",
                "state": "retryable",
                "current_stage": "marts",
            },
        ]
        assert [row[1] for row in marts_per_run] == ["failed", "failed"]
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_worker_keeps_stage_results_when_marts_fail(source_pipeline, tmp_path, monkeypatch):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    body = _write_source_snapshot(
        tmp_path, "marts-fail.gpkg", [{"reference_id": "only", "installed_capacity": 5.0}]
    )

    def failing_marts(engine=None):
        report = marts.MartsReport()
        report.errors = ["materialized view refresh failed"]
        return report

    monkeypatch.setattr(ingestion, "build_marts", failing_marts)
    s3.put("sources/solar.gpkg", "marts-fail-1", body)

    result = ingestion.process_one_message(
        _source_message("marts-fail-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert not result.acknowledged
    assert result.states == (ingestion.RunState.RETRYABLE,)
    with ENGINE.connect() as connection:
        run = connection.execute(
            text(
                f"SELECT state, current_stage FROM {schemas['service']}.ingestion_runs "
                "WHERE object_version_id = 'marts-fail-1'"
            )
        ).mappings().one()
        stages = connection.execute(
            text(
                f"SELECT stage, outcome FROM {schemas['service']}.stage_results "
                "ORDER BY stage"
            )
        ).mappings().all()
    assert dict(run) == {"state": "retryable", "current_stage": "marts"}
    assert [dict(stage) for stage in stages] == [
        {"stage": "extract", "outcome": "succeeded"},
        {"stage": "load", "outcome": "succeeded"},
        {"stage": "marts", "outcome": "failed"},
        {"stage": "transform", "outcome": "succeeded"},
    ]


def test_worker_keeps_a_message_with_an_unreadable_record(monkeypatch):
    """A record that cannot be read as an S3 identity is not dropped silently."""
    schema = f"service_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(ingestion, "SERVICE_SCHEMA", schema)
    s3 = FakeS3()
    sqs = FakeSQS()
    processor = FakeProcessor()
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
                                "versionId": "version-1",
                            },
                        },
                    },
                    {"eventSource": "aws:s3", "s3": {"bucket": {"name": "energy-data"}}},
                ]
            }
        ),
    )

    try:
        ingestion.bootstrap(
            ingestion.BootstrapConfig(bucket="energy-data"),
            engine=ENGINE,
            s3=s3,
        )
        result = ingestion.process_one_message(
            message,
            engine=ENGINE,
            s3=s3,
            sqs=sqs,
            sns=FakeSNS(),
            processor=processor,
        )

        # The readable record still loads, but the message is left for
        # redelivery rather than deleted with a record nobody claimed.
        assert [state.value for state in result.states] == ["succeeded"]
        assert not result.acknowledged
        assert sqs.deleted == []
    finally:
        with ENGINE.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def test_worker_ignores_events_for_unaccepted_keys(source_pipeline, tmp_path):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    body = _write_source_snapshot(tmp_path, "stray.gpkg", [{"reference_id": "stray"}])
    s3.put("random/whatever.gpkg", "stray-1", body)
    message = ingestion.SqsMessage(
        receipt_handle="receipt-stray",
        body=json.dumps(
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {"name": "energy-data"},
                            "object": {
                                "key": "random/whatever.gpkg",
                                "versionId": "stray-1",
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
        sns=FakeSNS(),
        processor=processor,
    )

    assert result.acknowledged
    assert result.states == ()
    assert s3.reads == []
    with ENGINE.connect() as connection:
        runs = connection.execute(
            text(
                f"SELECT run_id FROM {source_pipeline['schemas']['service']}"
                ".ingestion_runs"
            )
        ).scalars().all()
    assert list(runs) == []
    assert sqs.deleted == ["receipt-stray"]


def test_worker_marks_a_redelivered_version_stale_after_a_newer_one_loaded(
    source_pipeline, tmp_path
):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    s3.last_modified["v-old"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s3.last_modified["v-new"] = datetime(2026, 2, 3, tzinfo=timezone.utc)

    broken = _write_mixed_source_snapshot(tmp_path, "broken.gpkg")
    s3.put("sources/solar.gpkg", "v-old", broken)
    first = ingestion.process_one_message(
        _source_message("v-old"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert first.states == (ingestion.RunState.RETRYABLE,)

    current = _write_source_snapshot(
        tmp_path, "current.gpkg", [{"reference_id": "row", "installed_capacity": 2.0}]
    )
    s3.put("sources/solar.gpkg", "v-new", current)
    second = ingestion.process_one_message(
        _source_message("v-new"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert second.states == (ingestion.RunState.SUCCEEDED,)

    s3.current["sources/solar.gpkg"] = "v-old"
    reads_before = len(s3.reads)
    redelivered = ingestion.process_one_message(
        _source_message("v-old"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert redelivered.acknowledged
    assert redelivered.states == (ingestion.RunState.STALE,)
    assert len(s3.reads) == reads_before
    with ENGINE.connect() as connection:
        old_run = connection.execute(
            text(
                f"SELECT state, terminal_error FROM {schemas['service']}.ingestion_runs "
                "WHERE object_version_id = 'v-old'"
            )
        ).mappings().one()
    assert dict(old_run) == {
        "state": "stale",
        "terminal_error": (
            "Delayed object version v-old of sources/solar.gpkg "
            "is older than already-loaded v-new"
        ),
    }


def test_worker_keeps_other_sources_properties_when_loading_the_kind(
    source_pipeline, tmp_path
):
    """A whole-kind snapshot load must not strip the other sources' links.

    The property transfer deletes the whitelist links of every unit the load
    upserted, so it has to refill them from the whole kind, not just from the
    snapshot's own source.
    """
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]

    wind = _write_source_snapshot(
        tmp_path,
        "wind.gpkg",
        [
            {
                "energy_source": "Wind Energy",
                "reference_id": "wind-1",
                "location": "Offshore",
                "solar_type": None,
                "coordinates": (12.0, 52.0),
            }
        ],
    )
    s3.put("sources/wind.gpkg", "wind-1", wind)
    assert ingestion.process_one_message(
        _source_message("wind-1", source="wind"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    ).acknowledged
    before = _decomposed_properties(ENGINE, schemas["core"], "wind", "wind-1")
    assert before["location"] == "Offshore"

    solar = _write_source_snapshot(
        tmp_path, "solar.gpkg", [{"reference_id": "solar-1", "location": "Roof"}]
    )
    s3.put("sources/solar.gpkg", "solar-1", solar)
    assert ingestion.process_one_message(
        _source_message("solar-1"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    ).acknowledged

    after = _decomposed_properties(ENGINE, schemas["core"], "wind", "wind-1")
    assert after == before
    assert _decomposed_properties(ENGINE, schemas["core"], "solar", "solar-1")


def test_worker_keeps_a_redelivered_succeeded_version_succeeded(
    source_pipeline, tmp_path
):
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    s3.last_modified["v-first"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _write_source_snapshot(
        tmp_path, "first.gpkg", [{"reference_id": "row", "installed_capacity": 1.0}]
    )
    second = _write_source_snapshot(
        tmp_path, "second.gpkg", [{"reference_id": "row", "installed_capacity": 2.0}]
    )
    s3.put("sources/solar.gpkg", "v-first", first)
    assert ingestion.process_one_message(
        _source_message("v-first"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    ).acknowledged

    s3.put("sources/solar.gpkg", "v-second", second)
    assert ingestion.process_one_message(
        _source_message("v-second"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    ).acknowledged

    redelivered = ingestion.process_one_message(
        _source_message("v-first"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )

    assert redelivered.acknowledged
    assert redelivered.states == (ingestion.RunState.SUCCEEDED,)
    with ENGINE.connect() as connection:
        first_run = connection.execute(
            text(
                f"SELECT state, terminal_error FROM {schemas['service']}.ingestion_runs "
                "WHERE object_version_id = 'v-first'"
            )
        ).mappings().one()
        capacity = connection.execute(
            text(
                f"SELECT installed_capacity FROM {schemas['core']}.generators"
            )
        ).scalar()
    assert dict(first_run) == {"state": "succeeded", "terminal_error": None}
    assert capacity == 2.0


def test_worker_processes_authoritative_solar_snapshots_with_lineage(source_pipeline, tmp_path):
    initial = _write_source_snapshot(
        tmp_path,
        "version-1.gpkg",
        [
            {
                "reference_id": "keep",
                "installed_capacity": 100.0,
                "reference_date": "2024-01-01",
                "coordinates": (10.0, 50.0),
            },
            {
                "energy_source": "Solar energy",
                "reference_id": "reappear",
                "installed_capacity": 200.0,
                "reference_date": "2024-02-01",
                "coordinates": (10.1, 50.0),
            },
            {
                "reference_id": None,
                "installed_capacity": 50.0,
                "reference_date": "2023-01-01",
                "coordinates": (10.2, 50.0),
            },
        ],
    )
    newer = _write_source_snapshot(
        tmp_path,
        "version-2.gpkg",
        [
            {
                "reference_id": "keep",
                "installed_capacity": 150.0,
                "reference_date": "2000-01-01",
                "coordinates": (10.0, 50.0),
            },
            {
                "reference_id": "new-bad",
                "installed_capacity": None,
                "reference_date": "2025-01-01",
                "coordinates": (10.3, 50.0),
            },
        ],
    )
    latest = _write_source_snapshot(
        tmp_path,
        "version-3.gpkg",
        [
            {
                "reference_id": "keep",
                "installed_capacity": 160.0,
                "reference_date": "1999-01-01",
                "coordinates": (10.0, 50.0),
            },
            {
                "reference_id": "reappear",
                "installed_capacity": 225.0,
                "reference_date": "1998-01-01",
                "coordinates": (10.1, 50.0),
            },
            {
                "reference_id": None,
                "installed_capacity": 75.0,
                "reference_date": "1997-01-01",
                "coordinates": (10.2, 50.0),
            },
        ],
    )
    delayed = _write_source_snapshot(
        tmp_path,
        "version-0.gpkg",
        [{"reference_id": "never-seen", "coordinates": (10.4, 50.0)}],
    )
    s3 = source_pipeline["s3"]
    sqs = source_pipeline["sqs"]
    processor = source_pipeline["processor"]
    schemas = source_pipeline["schemas"]
    for version_id, body in (
        ("version-1", initial),
        ("version-2", newer),
    ):
        s3.put("sources/solar.gpkg", version_id, body)
        result = ingestion.process_one_message(
            _source_message(version_id),
            engine=ENGINE,
            s3=s3,
            sqs=sqs,
            sns=FakeSNS(),
            processor=processor,
        )
        assert result.acknowledged
        assert result.states == (ingestion.RunState.SUCCEEDED,)

    def rows(sql, parameters=None):
        with ENGINE.connect() as connection:
            return connection.execute(text(sql), parameters or {}).mappings().all()

    run_ids = {
        row["object_version_id"]: row["run_id"]
        for row in rows(
            f"SELECT run_id, object_version_id FROM {schemas['service']}.ingestion_runs"
        )
    }
    initial_members = {
        row["unit_key"]: row["bad_quality"]
        for row in rows(
            f"SELECT unit_key, bad_quality FROM {schemas['service']}.source_memberships "
            "WHERE run_id = :run_id",
            {"run_id": run_ids["version-1"]},
        )
    }
    newer_members = {
        row["reference_id"]: row["bad_quality"]
        for row in rows(
            f"SELECT reference_id, bad_quality FROM {schemas['service']}.source_memberships "
            "WHERE run_id = :run_id",
            {"run_id": run_ids["version-2"]},
        )
    }
    assert len(initial_members) == 3
    assert newer_members == {"keep": False, "new-bad": True}

    raw_tables = rows(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :schema ORDER BY table_name",
        {"schema": schemas["raw"]},
    )
    ledger = rows(
        f"SELECT object_version_id, loaded_to FROM {schemas['service']}.loaded_files "
        "WHERE object_key = 'sources/solar.gpkg' ORDER BY loaded_at"
    )
    assert len(raw_tables) == 2
    assert {row["object_version_id"] for row in ledger} == {
        "version-1",
        "version-2",
    }
    assert {row["loaded_to"] for row in ledger} == {
        row["table_name"] for row in raw_tables
    }

    core_after_newer = {
        row["reference_id"] or row["unit_id"]: row["installed_capacity"]
        for row in rows(
            f"SELECT unit_id, reference_id, installed_capacity "
            f"FROM {schemas['core']}.generators"
        )
    }
    assert len(core_after_newer) == 3
    assert core_after_newer["keep"] == 150.0
    assert core_after_newer["reappear"] == 200.0
    assert "new-bad" not in core_after_newer
    assert rows(
        f"SELECT state, energy_source, installation_count "
        f"FROM {schemas['marts']}.installation_counts "
        "WHERE energy_source = 'solar'"
    )[0]["installation_count"] == 3
    assert float(
        rows(
            f"SELECT generation_capacity FROM {schemas['marts']}.generation_capacity "
            "WHERE energy_source = 'solar'"
        )[0]["generation_capacity"]
    ) == 400.0

    synthetic_identity = next(
        unit_key
        for unit_key in initial_members
        if unit_key.startswith("syn_")
    )
    synthetic_core_id = rows(
        f"SELECT unit_id FROM {schemas['core']}.generators "
        "WHERE reference_id IS NULL"
    )[0]["unit_id"]

    s3.put("sources/solar.gpkg", "version-3", latest)
    latest_result = ingestion.process_one_message(
        _source_message("version-3"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert latest_result.acknowledged
    assert latest_result.states == (ingestion.RunState.SUCCEEDED,)
    assert len(
        rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema",
            {"schema": schemas["raw"]},
        )
    ) == 3

    s3.put("sources/solar.gpkg", "version-0", delayed)
    s3.current["sources/solar.gpkg"] = "version-3"
    stale_result = ingestion.process_one_message(
        _source_message("version-0"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert stale_result.acknowledged
    assert stale_result.states == (ingestion.RunState.STALE,)
    assert len(
        rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema",
            {"schema": schemas["raw"]},
        )
    ) == 3

    s3.put("sources/solar.gpkg", "version-3", latest)
    duplicate_result = ingestion.process_one_message(
        _source_message("version-3"),
        engine=ENGINE,
        s3=s3,
        sqs=sqs,
        sns=FakeSNS(),
        processor=processor,
    )
    assert duplicate_result.acknowledged
    assert duplicate_result.states == (ingestion.RunState.SUCCEEDED,)
    assert len(
        rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema",
            {"schema": schemas["raw"]},
        )
    ) == 3

    core_after_latest = {
        row["reference_id"] or row["unit_id"]: row["installed_capacity"]
        for row in rows(
            f"SELECT unit_id, reference_id, installed_capacity "
            f"FROM {schemas['core']}.generators"
        )
    }
    assert len(core_after_latest) == 3
    assert core_after_latest["keep"] == 160.0
    assert core_after_latest["reappear"] == 225.0
    assert synthetic_identity in initial_members
    assert {
        row["unit_id"]
        for row in rows(
            f"SELECT unit_id FROM {schemas['core']}.generators "
            "WHERE reference_id IS NULL"
        )
    } == {synthetic_core_id}
    assert {row["state"] for row in rows(
        f"SELECT state FROM {schemas['service']}.ingestion_runs"
    )} == {"succeeded", "stale"}
    assert {row["stage"] for row in rows(
        f"SELECT stage FROM {schemas['service']}.stage_results "
        f"WHERE run_id = :run_id",
        {"run_id": run_ids["version-2"]},
    )} >= {"extract", "transform", "load", "marts"}
