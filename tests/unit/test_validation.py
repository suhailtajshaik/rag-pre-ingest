from __future__ import annotations

import io
import zipfile

import pypdfium2 as pdfium
import pytest
from docx import Document
from openpyxl import Workbook
from PIL import Image

from rag_pre_ingest.pipeline.validation import (
    ValidationConfig,
    ValidationError,
    inspect_archive,
    validate_filename,
    validate_size,
    validate_upload,
)


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(output, format="PNG")
    return output.getvalue()


def pdf_bytes() -> bytes:
    output = io.BytesIO()
    with pdfium.PdfDocument.new() as document:
        document.new_page(100, 100).close()
        document.save(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "filename", ["../a.pdf", "a/b.pdf", "a\\b.pdf", "C:a.pdf", "", ".", "..", "a\x00.pdf"]
)
def test_unsafe_names(filename: str) -> None:
    with pytest.raises(ValidationError, match="plain file name") as error:
        validate_filename(filename)
    assert error.value.code == "unsafe_filename"


def test_safe_unicode_name() -> None:
    validate_filename("résumé final.pdf")


@pytest.mark.parametrize(("size", "code"), [(0, "empty_file"), (11, "file_too_large")])
def test_size_rejection(size: int, code: str) -> None:
    with pytest.raises(ValidationError) as error:
        validate_size(size, 10)
    assert error.value.code == code


def test_size_at_limit() -> None:
    validate_size(10, 10)


def test_image_and_wrong_extension() -> None:
    result = validate_upload(image_bytes(), "image.pdf", ValidationConfig())
    assert result.file_type == "png"
    assert result.page_count == 1
    assert result.extension_mismatch


def test_image_pixel_limit() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(image_bytes(), "image.png", ValidationConfig(max_image_pixels=99))
    assert error.value.code == "image_too_large"


def test_corrupted_image() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(image_bytes()[:40], "image.png", ValidationConfig())
    assert error.value.code == "corrupted_file"


def test_pdf() -> None:
    result = validate_upload(pdf_bytes(), "document.pdf", ValidationConfig())
    assert result.file_type == "pdf"
    assert result.page_count == 1


def test_corrupted_pdf() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(b"%PDF-1.7\ngarbage", "document.pdf", ValidationConfig())
    assert error.value.code == "corrupted_file"


def test_pdf_page_limit() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(pdf_bytes(), "document.pdf", ValidationConfig(max_pages=0))
    assert error.value.code == "too_many_pages"


@pytest.mark.parametrize("kind", ["docx", "xlsx"])
def test_office(kind: str) -> None:
    output = io.BytesIO()
    if kind == "docx":
        Document().save(output)
    else:
        workbook = Workbook()
        workbook.save(output)
        workbook.close()
    result = validate_upload(output.getvalue(), f"document.{kind}", ValidationConfig())
    assert result.file_type == kind
    assert not result.extension_mismatch


def archive_bytes(parts: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_missing_office_parts() -> None:
    with pytest.raises(ValidationError) as error:
        inspect_archive(archive_bytes({"word/document.xml": "<xml/>"}), ValidationConfig())
    assert error.value.code == "corrupted_file"


@pytest.mark.parametrize(
    "config", [ValidationConfig(max_zip_ratio=2), ValidationConfig(max_zip_uncompressed_bytes=10)]
)
def test_archive_expansion_limits(config: ValidationConfig) -> None:
    with pytest.raises(ValidationError) as error:
        inspect_archive(archive_bytes({"word/document.xml": "a" * 10000}), config)
    assert error.value.code == "archive_limit_exceeded"


def test_unsupported_bytes() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(b"plain text", "document.pdf", ValidationConfig())
    assert error.value.code == "unsupported_file_type"


def test_legacy_or_encrypted_office() -> None:
    with pytest.raises(ValidationError) as error:
        validate_upload(bytes.fromhex("d0cf11e0a1b11ae1"), "document.docx", ValidationConfig())
    assert error.value.code == "encrypted_or_legacy_office"


@pytest.mark.parametrize(
    ("format_name", "extension"),
    [("TIFF", "tif"), ("JPEG", "jpg"), ("GIF", "gif"), ("BMP", "bmp"), ("WEBP", "webp")],
)
def test_supported_image_aliases(format_name: str, extension: str) -> None:
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(output, format=format_name)
    result = validate_upload(output.getvalue(), f"image.{extension}", ValidationConfig())
    assert not result.extension_mismatch


def test_multiframe_page_limit() -> None:
    output = io.BytesIO()
    first = Image.new("RGB", (10, 10), "white")
    first.save(output, format="TIFF", save_all=True, append_images=[first])
    with pytest.raises(ValidationError) as error:
        validate_upload(output.getvalue(), "image.tiff", ValidationConfig(max_pages=1))
    assert error.value.code == "too_many_pages"


def test_archive_crc_corruption() -> None:
    data = archive_bytes(
        {
            "[Content_Types].xml": "<Types/>",
            "_rels/.rels": "<Relationships/>",
            "word/document.xml": "<document/>",
        }
    )
    corrupted = bytearray(data)
    position = data.index(b"word/document.xml") + len(b"word/document.xml")
    corrupted[position + 3] ^= 128
    with pytest.raises(ValidationError) as error:
        inspect_archive(bytes(corrupted), ValidationConfig())
    assert error.value.code == "corrupted_file"


def test_encrypted_archive_is_rejected() -> None:
    data = bytearray(archive_bytes({"word/document.xml": "<document/>"}))
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6] |= 1
    data[central + 8] |= 1
    with pytest.raises(ValidationError) as error:
        inspect_archive(bytes(data), ValidationConfig())
    assert error.value.code == "encrypted_file"


def test_duplicate_archive_entry_is_rejected() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("word/document.xml", "<document/>")
    with pytest.raises(ValidationError) as error:
        inspect_archive(output.getvalue(), ValidationConfig())
    assert error.value.code == "corrupted_file"
