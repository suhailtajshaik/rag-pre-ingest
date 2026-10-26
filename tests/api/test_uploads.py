import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from rag_pre_ingest.config import Settings
from rag_pre_ingest.main import create_app


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, format="PNG")
    return output.getvalue()


def test_upload_dedup_and_status(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path, worker_enabled=False))) as client:
        response = client.post("/v1/documents", files={"file": ("sample.png", image_bytes())})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        duplicate = client.post("/v1/documents", files={"file": ("copy.png", image_bytes())})
        assert duplicate.status_code == 200
        assert duplicate.json() == {"job_id": job_id, "status": "queued", "already_exists": True}
        status = client.get(f"/v1/jobs/{job_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "queued"
        assert status.json()["warnings"] == []
        assert len(list((tmp_path / "uploads").iterdir())) == 1


def test_invalid_uploads_and_missing_job(tmp_path: Path) -> None:
    with TestClient(
        create_app(Settings(data_dir=tmp_path, max_upload_bytes=100, worker_enabled=False))
    ) as client:
        for filename, data, code, status in [
            ("empty.pdf", b"", "empty_file", 400),
            ("large.pdf", b"x" * 101, "file_too_large", 413),
            ("bad.pdf", b"%PDF-1.7\nbroken", "corrupted_file", 400),
            ("unknown.exe", b"unknown", "unsupported_file_type", 400),
            ("../unsafe.png", image_bytes(), "unsafe_filename", 400),
        ]:
            response = client.post("/v1/documents", files={"file": (filename, data)})
            assert response.status_code == status
            assert response.json()["error"]["code"] == code
        assert client.post("/v1/documents").status_code == 422
        assert client.get("/v1/jobs/missing").json()["error"]["code"] == "job_not_found"


def test_wrong_extension_and_validation_before_dedup(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path, worker_enabled=False))) as client:
        response = client.post("/v1/documents", files={"file": ("actually.pdf", image_bytes())})
        job = client.get(f"/v1/jobs/{response.json()['job_id']}").json()
        assert job["file_type"] == "png"
        assert job["warnings"][0]["code"] == "extension_mismatch"
        response = client.post("/v1/documents", files={"file": ("../bad.png", image_bytes())})
        assert response.status_code == 400


def test_docs_and_restart_persistence(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        job_id = client.post("/v1/documents", files={"file": ("a.png", image_bytes())}).json()[
            "job_id"
        ]
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/v1/jobs/{job_id}").status_code == 200


def test_transport_body_limit(tmp_path: Path) -> None:
    with TestClient(
        create_app(Settings(data_dir=tmp_path, max_upload_bytes=100, worker_enabled=False))
    ) as client:
        response = client.post(
            "/v1/documents",
            content=b"x" * 70000,
            headers={"content-type": "multipart/form-data; boundary=abc"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"
