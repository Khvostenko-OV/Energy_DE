"""Unit tests for the shared container entrypoint (issue #34).

`docker/entrypoint.py` replaces the old `docker/entrypoint.sh` so the distroless
runtime image needs no shell.  Semantics are pinned to the shell original:

- when `DATA_ENV_FILE` is set, the file exists, and neither `DATABASE_URL` nor
  `VIZ_DATABASE_URL` is already set, the file is loaded via python-dotenv; when
  either URL is already supplied (or the file is absent/disabled) nothing is
  loaded at all — an operator-supplied URL always wins,
- the container command (`CMD` / compose `command`) is then `execvp`'d so the
  real process becomes PID 1 and receives SIGINT on `docker stop`.

The module is loaded by path (the `docker/` dir is a script home, not a Python
package, so there is no importable dotted path).
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

DOCKER_ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker" / "entrypoint.py"

SPEC = spec_from_file_location("etl_entrypoint", DOCKER_ENTRYPOINT)
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(autouse=True)
def _clean_url_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VIZ_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATA_ENV_FILE", raising=False)


@pytest.fixture
def fake_execvp(monkeypatch):
    calls = []

    def _execvp(file, args):
        calls.append((file, list(args)))

    monkeypatch.setattr("os.execvp", _execvp)
    return calls


@pytest.fixture
def fake_loaded(monkeypatch):
    loaded = []

    def _load(path):
        loaded.append(Path(path))

    monkeypatch.setattr("dotenv.load_dotenv", _load)
    return loaded


class TestEnvLoading:
    def test_loads_file_when_both_urls_unset(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: p == "/app/data/docker.env")
        monkeypatch.setenv("DATA_ENV_FILE", "/app/data/docker.env")

        MODULE.main(["etl-entrypoint", "python", "-m", "etl", "run-all"])

        assert fake_loaded == [Path("/app/data/docker.env")]

    def test_skips_file_when_database_url_is_set(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: True)
        monkeypatch.setenv("DATA_ENV_FILE", "/app/data/docker.env")
        monkeypatch.setenv("DATABASE_URL", "postgresql://operator")

        MODULE.main(["etl-entrypoint", "python", "-m", "etl"])

        assert fake_loaded == []

    def test_skips_file_when_viz_database_url_is_set(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: True)
        monkeypatch.setenv("DATA_ENV_FILE", "/app/data/docker.env")
        monkeypatch.setenv("VIZ_DATABASE_URL", "postgresql://operator")

        MODULE.main(["etl-entrypoint", "python", "-m", "etl"])

        assert fake_loaded == []

    def test_skips_file_when_data_env_file_unset(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: True)

        MODULE.main(["etl-entrypoint", "python", "-m", "etl"])

        assert fake_loaded == []

    def test_skips_file_when_file_missing(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        monkeypatch.setenv("DATA_ENV_FILE", "/app/data/docker.env")

        MODULE.main(["etl-entrypoint", "python", "-m", "etl"])

        assert fake_loaded == []


class TestCommandForwarding:
    def test_execvp_forwards_the_container_command(self, monkeypatch, fake_execvp):
        monkeypatch.setattr("os.path.isfile", lambda p: False)

        MODULE.main(["etl-entrypoint", "streamlit", "run", "viz/app.py", "--server.port", "8501"])

        assert fake_execvp == [
            (
                "streamlit",
                ["streamlit", "run", "viz/app.py", "--server.port", "8501"],
            )
        ]

    def test_execvp_replaces_the_process_after_loading(self, monkeypatch, fake_execvp, fake_loaded):
        monkeypatch.setattr("os.path.isfile", lambda p: True)
        monkeypatch.setenv("DATA_ENV_FILE", "/app/data/docker.env")

        MODULE.main(["etl-entrypoint", "python", "-m", "etl", "marts"])

        assert fake_loaded == [Path("/app/data/docker.env")]
        assert fake_execvp == [("python", ["python", "-m", "etl", "marts"])]

    def test_empty_command_is_a_clean_error(self, monkeypatch, fake_execvp):
        with pytest.raises(SystemExit) as exc:
            MODULE.main(["etl-entrypoint"])

        assert exc.value.code != 0
        assert fake_execvp == []