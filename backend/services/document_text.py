"""Deterministic text extraction and local OCR for clinical documents."""

from __future__ import annotations

import io
import logging
from typing import List

from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_OCR_PAGES = 30
OCR_DPI = 220
MIN_DIRECT_TEXT_LENGTH = 30
MAX_EXTRACTED_CHARACTERS = 100_000


def _normalize_text(text: str) -> str:
    lines = [
        line.rstrip()
        for line in str(text or "").replace("\x00", "").splitlines()
    ]

    normalized = "\n".join(lines).strip()
    return normalized[:MAX_EXTRACTED_CHARACTERS]


def _ocr_images(images: List[object]) -> str:
    """Run local Tesseract OCR over a bounded set of Pillow images."""
    try:
        import pytesseract
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ocr_dependency_missing",
                "message": "The local OCR service is not installed.",
            },
        ) from exc

    output = []

    for page_number, image in enumerate(
        images[:MAX_OCR_PAGES],
        start=1,
    ):
        try:
            # Preserve page boundaries so the AI can associate report
            # sections and extracted results with their approximate page.
            text = pytesseract.image_to_string(
                image,
                lang="eng",
                config="--oem 3 --psm 6",
            )

            output.append(
                f"--- PAGE {page_number} ---\n{text.strip()}"
            )
        except Exception as exc:
            logger.warning(
                "OCR failed on page %s: %s",
                page_number,
                exc,
            )
            output.append(
                f"--- PAGE {page_number} ---\n"
                "[OCR could not read this page]"
            )

    return _normalize_text("\n\n".join(output))


def _ocr_pdf(data: bytes) -> str:
    """Render a scanned PDF locally and run OCR on each bounded page."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ocr_dependency_missing",
                "message": "PDF OCR support is not installed.",
            },
        ) from exc

    try:
        images = convert_from_bytes(
            data,
            dpi=OCR_DPI,
            first_page=1,
            last_page=MAX_OCR_PAGES,
            fmt="png",
            grayscale=True,
            thread_count=1,
        )
    except Exception as exc:
        logger.warning("Scanned PDF rendering failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "pdf_ocr_failed",
                "message": "The scanned PDF could not be processed.",
            },
        ) from exc

    return _ocr_images(images)


def _ocr_image(data: bytes) -> str:
    """Run OCR on a PNG, JPEG, or TIFF image."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ocr_dependency_missing",
                "message": "Image OCR support is not installed.",
            },
        ) from exc

    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image = image.convert("L")

        # Prevent extremely large photographs from exhausting memory.
        max_dimension = 5000
        image.thumbnail(
            (max_dimension, max_dimension),
            Image.Resampling.LANCZOS,
        )
    except Exception as exc:
        logger.warning("Lab report image could not be opened: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "image_extraction_failed",
                "message": "The image report could not be read.",
            },
        ) from exc

    return _ocr_images([image])


def extract_document_text(filename: str, data: bytes) -> str:
    """Extract text from PDF, DOCX, TXT, PNG, JPEG, or TIFF.

    Text PDFs use direct extraction first. Local OCR is used only when the
    direct result contains too little readable text.
    """
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        direct_text = ""

        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))

            if len(reader.pages) > MAX_OCR_PAGES:
                logger.warning(
                    "PDF has %s pages; extraction is capped at %s",
                    len(reader.pages),
                    MAX_OCR_PAGES,
                )

            pages = [
                page.extract_text() or ""
                for page in reader.pages[:MAX_OCR_PAGES]
            ]

            direct_text = _normalize_text(
                "\n\n".join(
                    f"--- PAGE {index} ---\n{text}"
                    for index, text in enumerate(pages, start=1)
                )
            )
        except Exception as exc:
            logger.warning(
                "Direct PDF extraction failed; trying OCR: %s",
                exc,
            )

        if len(direct_text.strip()) >= MIN_DIRECT_TEXT_LENGTH:
            return direct_text

        logger.info(
            "PDF contains insufficient direct text; using local OCR."
        )
        return _ocr_pdf(data)

    if name.endswith(".docx"):
        try:
            from docx import Document

            document = Document(io.BytesIO(data))
            lines = [
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text and paragraph.text.strip()
            ]

            for table in document.tables:
                for row in table.rows:
                    line = " | ".join(
                        cell.text.strip()
                        for cell in row.cells
                        if cell.text and cell.text.strip()
                    )

                    if line:
                        lines.append(line)

            return _normalize_text("\n".join(lines))
        except Exception as exc:
            logger.warning("DOCX text extraction failed: %s", exc)
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "docx_extraction_failed",
                    "message": "The DOCX report could not be read.",
                },
            ) from exc

    if name.endswith(".txt"):
        return _normalize_text(
            data.decode(
                "utf-8",
                errors="ignore",
            )
        )

    if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        return _ocr_image(data)

    if name.endswith((".heic", ".heif")):
        raise HTTPException(
            status_code=415,
            detail={
                "code": "heic_ocr_not_enabled",
                "message": (
                    "Convert this HEIC image to JPG or PNG before upload."
                ),
            },
        )

    raise HTTPException(
        status_code=415,
        detail={
            "code": "unsupported_lab_report_type",
            "message": (
                "Upload a PDF, DOCX, TXT, PNG, JPG, JPEG, or TIFF "
                "lab report."
            ),
        },
    )
