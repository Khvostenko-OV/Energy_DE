"""Unit tests for the config data-path accessors (issue #33).

`sources_data_dir()` and `boundaries_manifest()` are read-at-call accessors
over the environment, so the ETL input paths are configurable via `.env`
without hardcoding `data/` paths into the CLI. Their defaults are anchored to
the repo root (not the CWD), matching how `DATABASE_URL` is loaded via
`load_dotenv`.
"""

from pathlib import Path

from etl.config import boundaries_manifest, sources_data_dir

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSourcesDataDir:
    def test_defaults_to_repo_sources_folder(self, monkeypatch):
        monkeypatch.delenv("SOURCES_DATA_DIR", raising=False)
        assert sources_data_dir() == REPO_ROOT / "data" / "sources"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("SOURCES_DATA_DIR", "/tmp/elsewhere/sources")
        assert sources_data_dir() == Path("/tmp/elsewhere/sources")


class TestBoundariesManifest:
    def test_defaults_to_repo_boundaries_manifest(self, monkeypatch):
        monkeypatch.delenv("BOUNDARIES_MANIFEST", raising=False)
        assert boundaries_manifest() == REPO_ROOT / "data" / "boundaries" / "boundaries.txt"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("BOUNDARIES_MANIFEST", "/tmp/elsewhere/boundaries.txt")
        assert boundaries_manifest() == Path("/tmp/elsewhere/boundaries.txt")