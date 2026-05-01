import logging
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

from striprtf.striprtf import rtf_to_text


def _is_stf_host(url: str) -> bool:
    # WSL sandboxes lack a full CA bundle; *.stf.jus.br content is public,
    # so verify=False is safe. Previously this list was hard-coded to
    # "sistemas.stf.jus.br" only, which left digital.stf.jus.br (newer
    # monocratic-decisions API) failing SSL on 2023+ sweeps.
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "stf.jus.br" or host.endswith(".stf.jus.br")


try:
    from pypdf import PdfReader

    PDF_AVAILABLE = True
except ImportError:
    PdfReader = None  # type: ignore
    PDF_AVAILABLE = False


def detect_file_type(response) -> str:
    """Detect if the response contains PDF or RTF content"""
    content_type = response.headers.get("content-type", "").lower()
    content = response.content[:100]  # First 100 bytes

    if content.startswith(b"%PDF"):
        return "pdf"
    elif content.startswith(b"{\\rtf") or "rtf" in content_type:
        return "rtf"
    else:
        return "unknown"


def extract_pdf_text_from_content(content: bytes) -> Optional[str]:
    """Extract text from PDF content using PyPDF"""
    if not PDF_AVAILABLE:
        raise ImportError("PyPDF is not available")

    try:
        reader = PdfReader(BytesIO(content))  # type: ignore
        text = ""

        for page in reader.pages:
            # "plain" emits running prose; "layout" preserved x-coordinate
            # gaps, which reproduced STF's letter-spaced titles as
            # `O S   ENHOR  M  INISTRO` and forced downstream re-collapsing.
            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

        return text.strip() if text else None
    except Exception as e:
        logging.debug(f"PyPDF failed: {e}")
        return None


def extract_rtf_text(content: bytes) -> Optional[str]:
    """Extract text from RTF content"""
    try:
        # STF RTFs escape accented bytes as \'XX hex pairs in the source
        # stream, not as raw UTF-8. striprtf resolves those internally, so
        # latin-1 decode preserves the byte stream losslessly before parsing.
        rtf_text = content.decode("latin-1", errors="ignore")
        plain_text = rtf_to_text(rtf_text)
        return plain_text.strip()
    except Exception as e:
        logging.warning(f"Failed to extract RTF text: {e}")
        return None


