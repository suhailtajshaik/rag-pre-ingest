"""Run inside the built container with /fixtures mounted read-only."""

import ast
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8000"


def get(path: str) -> Any:
    return urllib.request.urlopen(BASE + path, timeout=60)


def upload(path: Path) -> tuple[int, dict[str, Any]]:
    body = (
        b'--sample\r\nContent-Disposition: form-data; name="file"; filename="'
        + path.name.encode()
        + b'"\r\nContent-Type: application/octet-stream\r\n\r\n'
        + path.read_bytes()
        + b"\r\n--sample--\r\n"
    )
    request = urllib.request.Request(
        BASE + "/v1/documents",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=sample"},
    )
    with urllib.request.urlopen(request) as response:
        return response.status, json.load(response)


def main() -> None:
    assert os.getuid() != 0, "Container must run as a non-root user"
    server = subprocess.Popen(
        ["uvicorn", "rag_pre_ingest.main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                assert get("/").status == 200 and get("/docs").status == 200
                break
            except OSError:
                time.sleep(0.1)
        for file, expected in [
            ("synthetic/04-ruled-table.pdf", ["9.50"]),
            ("user_samples/hackathon-guidelines.png", ["provided datasets"]),
            (
                "user_samples/theme-palette.png",
                ["#D4DDD5", "#151E16", "#253026", "#16A34A", "#4ADE80"],
            ),
            ("user_samples/python-code.png", ['"content": "What is the capital of France?"']),
            ("user_samples/theme-cards.png", ["Dark·Minimal·Monochrome", "Dark·Deep blue"]),
            (
                "user_samples/ml-cyber-roles.pdf",
                ["MLOps Engineer / Senior MLOps Engineer", "Data Engineer (ML-focused)"],
            ),
            (
                "user_samples/numbered-questions.png",
                [
                    "1. DO I LIKE WHO I AM WHEN I'M AROUND THEM?",
                    "2. DO THEY CHALLENGE ME IN WAYS THAT ELEVATE ME?",
                    "3. DOES MY BEHAVIOR MOVE ME CLOSER OR FURTHER FROM MY VALUES?",
                ],
            ),
            ("user_samples/sales-sheet.png", ["599.99", "Home Appliances", "1999.98"]),
            ("user_samples/learning-levels.png", ["Level 1", "Integrate connectors", "Level 5"]),
            ("user_samples/tech-stack.png", ["Object storage", "AI models", "DigitalOcean"]),
            ("user_samples/automation-workshop.png", ["Google Sheets", "Understanding Trigger"]),
            (
                "user_samples/llm-flowchart.png",
                [
                    "Tokenization → Embedding → Transformer Mechanism → "
                    "Prediction → Response Generation"
                ],
            ),
        ]:
            path = Path("/fixtures") / file
            status, job = upload(path)
            assert status == 202
            job_id = job["job_id"]
            with get(f"/v1/jobs/{job_id}/events") as events:
                assert events.readline().startswith(b"event: progress")
            for _ in range(600):
                with get(f"/v1/jobs/{job_id}") as response:
                    current = json.load(response)
                if current["status"] in ("done", "failed"):
                    break
                time.sleep(0.1)
            assert current["status"] == "done", current
            with get(f"/v1/jobs/{job_id}/result") as response:
                result = json.load(response)
            assert all(text in result["markdown"] for text in expected), result
            assert get(f"/v1/jobs/{job_id}/markdown").status == 200
            assert get(f"/v1/jobs/{job_id}/pages/1/image").read().startswith(b"\x89PNG")
            if "hackathon" in file:
                assert result["stats"]["lists"] == 23
                assert not any(line.strip() == "O" for line in result["markdown"].splitlines())
            if "numbered-questions" in file:
                assert result["stats"]["lists"] == 3
            if "automation-workshop" in file:
                assert result["stats"]["lists"] == 3
                assert "里" not in result["markdown"]
                assert "- slack" not in result["markdown"]
            if "llm-flowchart" in file:
                assert sum(len(page["connectors"]) for page in result["pages"]) == 4
                assert result["stats"]["tables"]["total"] == 0
            if "tech-stack" in file:
                phrases = [
                    "Database",
                    "MongoDB",
                    "Auth / Login",
                    "clerk",
                    "Emails",
                    "Resend",
                    "Cloud / VMs",
                    "DigitalOcean",
                    "Object storage",
                    "CLOUDFLARE",
                    "AI models",
                    "Gemini",
                ]
                positions = [result["markdown"].find(phrase) for phrase in phrases]
                assert all(p >= 0 for p in positions) and positions == sorted(positions)
            if "learning-levels" in file:
                phrases = [
                    "Level 1",
                    "Master advanced prompting",
                    "Level 2",
                    "Integrate connectors",
                    "Level 3",
                    "Learn about Diffusion Models",
                    "Level 4",
                    "Build complex automations",
                    "Level 5",
                    "Build a real world",
                ]
                positions = [result["markdown"].find(phrase) for phrase in phrases]
                assert all(position >= 0 for position in positions)
                assert positions == sorted(positions), "Level/description pair order lost"
            if "sales-sheet" in file:
                tables = [b for p in result["pages"] for b in p["blocks"] if b["type"] == "table"]
                assert len(tables) == 1 and tables[0]["columns"] == 9 and tables[0]["rows"] == 31
                cells = {(c["row"], c["col"]): c["text"] for c in tables[0]["cells"]}
                assert cells[(8, 5)] == "599.99" and cells[(12, 4)] == "3"
                assert cells[(30, 8)] == "Credit Card"
            if "theme-palette" in file:
                assert result["stats"]["tables"]["total"] == 2
            if "ml-cyber-roles" in file:
                assert result["stats"]["tables"]["total"] == 2
                assert result["stats"]["pages"]["ocr"] == 0
                assert "<br>" not in result["markdown"]
                table = next(b for b in result["pages"][1]["blocks"] if b["type"] == "table")
                assert not any(cell["is_header"] for cell in table["cells"])
            if "python-code" in file:
                code = next(
                    b
                    for b in result["pages"][0]["blocks"]
                    if b["markdown"].startswith("```python\n")
                )
                ast.parse(code["text"])
                assert result["stats"]["lists"] == 0
            if "theme-cards" in file:
                assert result["markdown"].count("Try free") == 10
                assert result["markdown"].index("Dark·Teal·Electric") < result["markdown"].index(
                    "Light·Pink·Soft"
                )
            status, duplicate = upload(path)
            assert status == 200 and duplicate["job_id"] == job_id
            request = urllib.request.Request(BASE + f"/v1/jobs/{job_id}", method="DELETE")
            assert urllib.request.urlopen(request).status == 204
            try:
                get(f"/v1/jobs/{job_id}")
                raise AssertionError("Deleted job survived")
            except urllib.error.HTTPError as error:
                assert error.code == 404
            print("Container scenario passed: " + path.name, flush=True)
        print(
            "Docker smoke passed: viewer, Swagger, SSE, tables, local OCR, lists, results, "
            "previews, dedup, deletion, non-root.",
            flush=True,
        )
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
