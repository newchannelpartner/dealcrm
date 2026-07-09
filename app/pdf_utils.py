"""PDF text extraction with an OCR fallback for scanned/image-only PDFs.

Uses PyMuPDF (fitz) for both native text extraction and page rasterization, so no
Poppler dependency is needed. OCR uses Tesseract via pytesseract — that requires the
Tesseract binary to be installed on the host (see README / Dockerfile).
"""
import io
import os
import logging

logger = logging.getLogger(__name__)

# If a page's embedded text layer has at least this many characters, we treat the PDF
# as a real text PDF and skip OCR. Scanned PDFs typically yield ~0 characters.
MIN_TEXT_CHARS = 40
# Cap OCR work so a huge scanned document can't hang the request.
MAX_OCR_PAGES = 15
OCR_DPI = 200


class OcrUnavailable(Exception):
    """Raised when a scanned PDF needs OCR but Tesseract isn't installed."""


def extract_pdf_text(data: bytes) -> tuple[str, bool]:
    """Extract text from a PDF's bytes.

    Returns (text, used_ocr). Tries the embedded text layer first; if the document has
    little or no extractable text (i.e. it's scanned), falls back to OCR.
    Raises OcrUnavailable if OCR is needed but Tesseract isn't installed.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        parts = [page.get_text() for page in doc]
        text = "\n".join(parts).strip()
        if len(text) >= MIN_TEXT_CHARS:
            return text, False
        # Little/no embedded text → scanned document, try OCR.
        ocr_text = _ocr_document(doc)
        return ocr_text.strip(), True
    finally:
        doc.close()


def _ocr_document(doc) -> str:
    """Render each page to an image and OCR it with Tesseract."""
    import pytesseract
    from PIL import Image

    # Allow pointing at a specific Tesseract binary (common on Windows).
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    out = []
    for i, page in enumerate(doc):
        if i >= MAX_OCR_PAGES:
            logger.warning("PDF has more than %d pages; OCR truncated.", MAX_OCR_PAGES)
            break
        pix = page.get_pixmap(dpi=OCR_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            out.append(pytesseract.image_to_string(img))
        except pytesseract.TesseractNotFoundError as e:
            raise OcrUnavailable(
                "This PDF has no selectable text and needs OCR, but Tesseract isn't "
                "installed. Install it (Windows: `winget install UB-Mannheim.TesseractOCR`; "
                "Linux: `apt-get install tesseract-ocr`) and try again."
            ) from e
    return "\n".join(out)
