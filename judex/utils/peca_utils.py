import logging
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

import requests
from striprtf.striprtf import rtf_to_text
import urllib3

# Must match the scraper session's User-Agent — STF's WAF permanently
# 403s non-browser UAs (`python-requests/*`) per docs/stf-portal.md. This
# previously bit any `portal.stf.jus.br` RTF/PDF silently; sistemas/digital
# origins happen to be more permissive but the UA cost here is zero.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


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

# Suppress urllib3 warnings for STF URLs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


def extract_document_text(
    url: str, timeout: int = 30
) -> tuple[Optional[str], Optional[str]]:
    """Extract text from a PDF or RTF URL.

    Returns `(text, extractor)` where `extractor` is "pypdf_plain" when
    the PDF text layer parsed, "rtf" when the RTF branch ran, or None
    when the file type could not be recognised. When extraction fails
    the text side is None but the extractor label still reflects which
    branch was tried, so callers can distinguish "empty PDF" from
    "empty RTF" in provenance records.
    """
    if not url:
        return (None, None)

    try:
        # Download the document with SSL verification disabled for STF URLs
        verify_ssl = not _is_stf_host(url)
        response = requests.get(
            url, timeout=timeout, verify=verify_ssl,
            headers={"User-Agent": _BROWSER_UA},
        )
        response.raise_for_status()

        # Detect file type
        file_type = detect_file_type(response)
        logging.debug(f"Detected file type: {file_type}")

        if file_type == "pdf":
            try:
                text = extract_pdf_text_from_content(response.content)
            except Exception as e:
                logging.warning(f"Failed to extract PDF text: {e}")
                return (None, "pypdf_plain")
            return (text, "pypdf_plain")
        elif file_type == "rtf":
            try:
                text = extract_rtf_text(response.content)
            except Exception as e:
                logging.warning(f"Failed to extract RTF text: {e}")
                return (None, "rtf")
            return (text, "rtf")
        else:
            logging.warning(f"Unknown file type for {url}: {file_type}")
            return (None, None)

    except requests.RequestException as e:
        logging.warning(f"Failed to download document from {url}: {e}")
        return (None, None)
    except Exception as e:
        logging.warning(f"Failed to extract text from document {url}: {e}")
        return (None, None)
