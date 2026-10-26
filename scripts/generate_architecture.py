"""Generate editable native Excalidraw and matching SVG using standard library only."""

from __future__ import annotations

import hashlib
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1600, 1830
COLORS = {
    "read": "#e7f0ff",
    "ocr": "#daf5ed",
    "output": "#eee8ff",
    "warning": "#fff2cc",
    "neutral": "#f3f5f8",
}


def generate() -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    svg: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
            f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        ),
        (
            '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" '
            'refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" '
            'fill="#475569"/></marker></defs>'
        ),
        '<rect width="1600" height="1830" fill="white"/>',
    ]

    def base(
        identifier: str, kind: str, x: float, y: float, width: float, height: float
    ) -> dict[str, Any]:
        return {
            "id": identifier,
            "type": kind,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": "#334155",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1.5,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": int(hashlib.sha256(identifier.encode()).hexdigest()[:7], 16),
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
            "boundElements": None,
            "updated": 0,
            "created": None,
            "link": None,
            "locked": False,
        }

    def text(
        identifier: str, x: float, y: float, value: str, size: int = 20, color: str = "#0f172a"
    ) -> None:
        lines = value.split("\n")
        width = max(len(line) for line in lines) * size * 0.59
        height = len(lines) * size * 1.3
        element = base(identifier, "text", x, y, width, height)
        element.update(
            {
                "strokeColor": color,
                "fontSize": size,
                "fontFamily": 2,
                "text": value,
                "originalText": value,
                "textAlign": "left",
                "verticalAlign": "top",
                "containerId": None,
                "autoResize": True,
                "lineHeight": 1.3,
                "baseline": size,
            }
        )
        elements.append(element)
        svg.append(
            f'<text x="{x}" y="{y + size}" font-family="Helvetica,Arial,sans-serif" '
            f'font-size="{size}" fill="{color}">'
        )
        for index, line in enumerate(lines):
            svg.append(
                f'<tspan x="{x}" dy="{0 if index == 0 else size * 1.3}">{html.escape(line)}</tspan>'
            )
        svg.append("</text>")

    def box(
        identifier: str,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        body: str,
        color: str = "neutral",
    ) -> None:
        element = base(identifier, "rectangle", x, y, w, h)
        element["backgroundColor"] = COLORS[color]
        elements.append(element)
        svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" '
            f'fill="{COLORS[color]}" stroke="#334155" stroke-width="1.5"/>'
        )
        text(identifier + "-title", x + 18, y + 14, title, 21)
        text(identifier + "-body", x + 18, y + 49, body, 17)
        for item in elements[-3:]:
            item["groupIds"] = [identifier + "-group"]

    def arrow(
        identifier: str,
        points: list[tuple[float, float]],
        label: str = "",
        label_at: tuple[float, float] | None = None,
        dashed: bool = False,
    ) -> None:
        x = min(p[0] for p in points)
        y = min(p[1] for p in points)
        w = max(p[0] for p in points) - x
        h = max(p[1] for p in points) - y
        element = base(identifier, "arrow", x, y, w, h)
        element.update(
            {
                "strokeColor": "#475569",
                "strokeStyle": "dashed" if dashed else "solid",
                "points": [[a - x, b - y] for a, b in points],
                "lastCommittedPoint": None,
                "startBinding": None,
                "endBinding": None,
                "startArrowhead": None,
                "endArrowhead": "arrow",
                "elbowed": False,
            }
        )
        elements.append(element)
        coords = " ".join(f"{a},{b}" for a, b in points)
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        svg.append(
            f'<polyline points="{coords}" fill="none" stroke="#475569" '
            f'stroke-width="1.7" marker-end="url(#arrow)"{dash}/>'
        )
        if label and label_at:
            text(identifier + "-label", *label_at, label, 15, "#475569")

    text("title", 70, 30, "rag-pre-ingest | current architecture", 32)
    text(
        "subtitle",
        70,
        80,
        "One service, local storage, direct reading first; OCR only where flagged.",
        20,
        "#475569",
    )
    text("service-label", 70, 122, "SERVICE AND STORAGE", 17, "#64748b")
    box(
        "viewer",
        70,
        160,
        440,
        110,
        "Vite + React viewer",
        "Static build served by FastAPI\nUpload, inspect, monitor and delete",
        "read",
    )
    box(
        "swagger",
        1090,
        160,
        440,
        110,
        "Swagger / API clients",
        "Automatic OpenAPI documentation\nSame FastAPI HTTP service",
        "read",
    )
    box(
        "api",
        580,
        280,
        440,
        150,
        "FastAPI routes + services",
        (
            "Thin routes; typed API models\nGET status, results, markdown, "
            "images\nSSE events; DELETE with worker lock"
        ),
        "read",
    )
    arrow("viewer-api", [(510, 215), (550, 215), (550, 305), (580, 305)])
    arrow("swagger-api", [(1090, 215), (1050, 215), (1050, 305), (1020, 305)])
    box(
        "door",
        70,
        340,
        440,
        160,
        "Upload validation door",
        (
            "Size, sniffed type, safe filename\nPDF / Office ZIP / image "
            "integrity\nPage, pixel and ZIP expansion caps\nReject first; stable "
            "error + audit"
        ),
        "warning",
    )
    arrow("api-door", [(580, 375), (510, 375)], "upload", (516, 346))
    box(
        "dedup",
        580,
        475,
        440,
        120,
        "Hash + exact duplicate check",
        "SHA-256 after validation succeeds\nUnique hash; reuse the existing job",
        "read",
    )
    arrow("door-hash", [(290, 500), (290, 535), (580, 535)], "validated bytes", (345, 509))
    box(
        "sqlite",
        1090,
        340,
        440,
        160,
        "SQLite in WAL mode",
        (
            "Durable jobs and queue state\nUnique hashes, progress and result "
            "paths\nRejected-upload audit\nRestart requeues unfinished jobs"
        ),
    )
    arrow("dedup-db", [(1020, 535), (1050, 535), (1050, 420), (1090, 420)])
    box(
        "uploads",
        1090,
        535,
        440,
        110,
        "Local upload storage",
        "Generated names; original bytes retained\nClient names never become paths",
    )
    arrow("db-uploads", [(1310, 500), (1310, 535)])
    box(
        "worker",
        70,
        665,
        950,
        150,
        "Durable background worker",
        (
            "Claims queued jobs; runs one isolated processing child at a "
            "time\nPer-job + per-page limits; temporary workspace; durable "
            "checkpoints\nInterrupted page work becomes warnings; recovered output "
            "remains inspectable\nDELETE cancels active work under lock and removes "
            "stored artifacts"
        ),
        "read",
    )
    arrow(
        "db-worker",
        [(1090, 455), (1060, 455), (1060, 645), (545, 645), (545, 665)],
        "claim queued job",
        (590, 617),
    )
    box(
        "results-storage",
        1090,
        665,
        440,
        150,
        "Local result storage",
        (
            "Result JSON and clean markdown\nPage PNG previews and image crops\nAPI "
            "reads persisted artifacts\nSSE reads current job progress"
        ),
        "output",
    )
    text("pipeline-label", 70, 866, "PROCESSING CHILD | per-page flow", 20, "#64748b")
    box(
        "reader",
        70,
        930,
        440,
        190,
        "Direct read always runs",
        (
            "PDFium: text, word boxes, vector lines\nWord: paragraphs, tables, image "
            "assets\nExcel: cells, merges, worksheet images\nStandalone images have "
            "no text layer\nOffice coordinates are synthetic"
        ),
        "read",
    )
    arrow("worker-reader", [(290, 815), (290, 930)], "process document", (307, 883))
    box(
        "quality",
        580,
        930,
        440,
        190,
        "Concurrent page quality checks",
        (
            "Runs alongside direct reading\nCharacter count, garbage, image "
            "coverage\nDensity and configurable thresholds\nNondecorative embedded "
            "image regions\nFlag only necessary pages / regions"
        ),
        "warning",
    )
    arrow("reader-quality", [(510, 990), (580, 990)], "page", (525, 962))
    box(
        "ocr",
        1090,
        930,
        440,
        190,
        "Flagged OCR only",
        (
            "RapidOCR + local ONNX models\nConcurrent region tasks; cached "
            "engines\nBounded render / crop / upscale\nNo runtime model "
            "download\nClean pages never enter OCR"
        ),
        "ocr",
    )
    arrow("quality-ocr", [(1020, 990), (1090, 990)], "flagged", (1024, 962))
    box(
        "reconcile",
        70,
        1210,
        440,
        180,
        "Reconcile sources + images",
        (
            "Keep readable direct text on disagreement\nFlag uncertain source "
            "conflicts\nPreserve image crops in JSON\nRepeated small logos marked "
            "decorative\nNever insert image placeholders"
        ),
        "read",
    )
    arrow("direct-merge", [(290, 1120), (290, 1210)], "direct blocks", (307, 1153))
    arrow(
        "ocr-merge",
        [(1310, 1120), (1310, 1170), (530, 1170), (530, 1250), (510, 1250)],
        "OCR blocks + confidence",
        (840, 1140),
    )
    box(
        "layout",
        580,
        1210,
        440,
        180,
        "Shared layout regions",
        (
            "Preserved source observations\nExplicit region boundaries and provenance\n"
            "Boundary-aware line grouping\nTables, cards and column reading order\n"
            "Recognition / layout confidence"
        ),
        "read",
    )
    arrow("merge-layout", [(510, 1320), (580, 1320)])
    box(
        "sanitizer",
        1090,
        1210,
        440,
        180,
        "Markdown sanitizer",
        (
            "Text-only Unicode and whitespace\nHyphens and list "
            "syntax\nFont-ranked heading levels + paths\nStrip repeated headers / "
            "footers\nTables keep a consistent column count"
        ),
        "output",
    )
    arrow("layout-sanitizer", [(1020, 1320), (1090, 1320)])
    box(
        "outputs",
        70,
        1470,
        950,
        150,
        "Published outputs",
        (
            "Clean markdown is the sole ingestion source: real content "
            "only\nStructured JSON: pages, typed blocks, boxes, sources, confidence, "
            "stats and warnings\nImages remain JSON assets; OCR text and captions "
            "become real text\nCheckpoints preserve progress; one bad page or block "
            "does not fail the document"
        ),
        "output",
    )
    arrow("sanitize-output", [(1310, 1390), (1310, 1430), (545, 1430), (545, 1470)])
    box(
        "warnings",
        1090,
        1470,
        440,
        150,
        "Warnings stay visible",
        (
            "Corrupted or timed-out pages\nEmpty output and uncertain OCR\nViewer "
            "warning panel + result JSON\nConfidence is provisional"
        ),
        "warning",
    )
    arrow("output-warnings", [(1020, 1545), (1090, 1545)])
    arrow(
        "publish-artifacts",
        [(1530, 1545), (1570, 1545), (1570, 745), (1530, 745)],
        "persist",
        (1501, 1400),
    )
    text(
        "legend",
        70,
        1665,
        (
            "BLUE: direct read / service    TEAL: OCR    PURPLE: outputs    AMBER: "
            "validation / warnings"
        ),
        17,
        "#475569",
    )
    text("outscope", 70, 1715, "Scope boundary", 21)
    text(
        "outscope-body",
        70,
        1750,
        (
            "No embeddings, chunking, vector search, LLM answering, authentication or "
            "URL ingestion.\nA separate downstream RAG system may consume clean "
            "markdown; it is outside this service."
        ),
        18,
        "#475569",
    )
    svg.append("</svg>")
    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    docs = ROOT / "docs"
    (docs / "architecture.excalidraw").write_text(json.dumps(scene, indent=2) + "\n")
    (docs / "architecture.svg").write_text("\n".join(svg) + "\n")
    (docs / "architecture.md").write_text("""# rag-pre-ingest architecture

[Editable Excalidraw scene](architecture.excalidraw) · [SVG preview](architecture.svg)

Open the `.excalidraw` file in Excalidraw using **Open** or drag it onto the canvas. Every box,
arrow and text label is editable. The SVG is a matching static preview.

The FastAPI service serves the React viewer and Swagger documentation. Upload validation
precedes hashing and deduplication. SQLite WAL stores the durable queue, job progress, hashes,
rejected-upload audit and output paths; generated filenames protect local uploads.

The background worker runs each job in an isolated child with time limits, temporary workspaces
and checkpoints. Direct reading always runs. Per-page quality checks overlap reading, and only
flagged image regions or broken pages enter concurrent local OCR. Source reconciliation retains
readable direct text and flags disagreement.

Source observations and explicit region boundaries make layout transformations inspectable.
Boundary-aware geometric grouping precedes final reading order; the final sanitizer cleans text.
Recognition and layout confidence are tracked separately. Layout, captions, tables and ordered
sanitizer steps produce clean markdown and structured JSON.
Blank and merged cells, image assets, provenance and warnings remain inspectable. Office
previews use synthetic page coordinates. Result, image, status and event endpoints power the
viewer; deletion cancels work under a shared lock before removing artifacts.

Clean markdown contains no image placeholders. Downstream embeddings, chunking and RAG are
outside this service, as are authentication, URL ingestion and LLM answering.

Regenerate both views with `python scripts/generate_architecture.py`. The generator uses only
the standard library. The native scene follows the [official Excalidraw JSON
schema](https://docs.excalidraw.com/docs/codebase/json-schema/).
""")
    loaded = json.loads((docs / "architecture.excalidraw").read_text())
    assert loaded["type"] == "excalidraw" and loaded["version"] == 2
    assert len({e["id"] for e in elements}) == len(elements)
    assert all(
        e["x"] >= 0 and e["y"] >= 0 and e["width"] >= 0 and e["height"] >= 0 for e in elements
    )
    assert all(e["x"] + e["width"] <= WIDTH and e["y"] + e["height"] <= HEIGHT for e in elements)
    by_id = {element["id"]: element for element in elements}
    for element in elements:
        if element["type"] != "text" or not element["id"].endswith(("-title", "-body")):
            continue
        container = by_id.get(element["id"].rsplit("-", 1)[0])
        if container is None or container["type"] != "rectangle":
            continue
        assert element["x"] + element["width"] <= container["x"] + container["width"] - 10
        assert element["y"] + element["height"] <= container["y"] + container["height"] - 6
    ET.parse(docs / "architecture.svg")
    print(f"Generated and validated {len(elements)} editable elements and matching SVG.")
    return scene


if __name__ == "__main__":
    generate()
