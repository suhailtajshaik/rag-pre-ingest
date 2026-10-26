from pathlib import Path

from fastapi.testclient import TestClient

from rag_pre_ingest.config import Settings
from rag_pre_ingest.main import create_app


def test_static_viewer_preserves_api_and_docs(tmp_path: Path) -> None:
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<html>Document workspace</html>")
    with TestClient(
        create_app(Settings(data_dir=tmp_path / "data", viewer_dir=viewer, worker_enabled=False))
    ) as client:
        assert "Document workspace" in client.get("/").text
        assert client.get("/docs").status_code == 200
        assert client.get("/v1/jobs").json() == []
        assert client.get("/v1/jobs/missing").status_code == 404
