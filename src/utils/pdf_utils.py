import logging
from io import BytesIO
from typing import Optional

import urllib3

# Suppress urllib3 warnings for STF URLs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
import striprtf  # type: ignore

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
        return None

    try:
        reader = PdfReader(BytesIO(content))  # type: ignore
        text = ""

        for page in reader.pages:
            # Try layout mode first for better formatting
            try:
                page_text = page.extract_text(extraction_mode="layout")
            except Exception:
                # Fallback to default extraction
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
        # Decode RTF content
        rtf_text = content.decode("utf-8", errors="ignore")
        # Strip RTF formatting
        plain_text = striprtf.rtf_to_text(rtf_text)  # type: ignore
        return plain_text.strip()
    except Exception as e:
        logging.warning(f"Failed to extract RTF text: {e}")
        return None


def extract_document_text(url: str, timeout: int = 30) -> Optional[str]:
    """
    Extract text from a PDF or RTF URL.

    Args:
        url: URL to the document
        timeout: Request timeout in seconds

    Returns:
        Extracted text or None if failed
    """
    if not url:
        return None

    try:
        # Download the document with SSL verification disabled for STF URLs
        verify_ssl = not url.startswith("https://sistemas.stf.jus.br")
        response = requests.get(url, timeout=timeout, verify=verify_ssl)
        response.raise_for_status()

        # Detect file type
        file_type = detect_file_type(response)
        logging.debug(f"Detected file type: {file_type} for {url}")

        if file_type == "pdf":
            return extract_pdf_text_from_content(response.content)
        elif file_type == "rtf":
            return extract_rtf_text(response.content)
        else:
            logging.warning(f"Unknown file type for {url}: {file_type}")
            return None

    except requests.RequestException as e:
        logging.warning(f"Failed to download document from {url}: {e}")
        return None
    except Exception as e:
        logging.warning(f"Failed to extract text from document {url}: {e}")
        return None


def extract_pdf_text(url: str, timeout: int = 30) -> Optional[str]:
    """
    Extract text from a PDF URL (legacy function for backward compatibility).

    Args:
        url: URL to the PDF
        timeout: Request timeout in seconds

    Returns:
        Extracted text or None if failed
    """
    return extract_document_text(url, timeout)


def extract_pdf_texts_from_session(session_data: dict) -> dict:
    """
    Extract document texts from session data URLs.

    Args:
        session_data: Session data dictionary with url_relatorio and url_voto

    Returns:
        Updated session data with conteudo_relatorio and conteudo_voto
    """
    # Extract relatorio text
    if session_data.get("url_relatorio"):
        relatorio_text = extract_document_text(session_data["url_relatorio"])
        if relatorio_text:
            session_data["conteudo_relatorio"] = relatorio_text
            logging.debug(
                f"Extracted {len(relatorio_text)} chars from relatorio document"
            )
        else:
            logging.warning(
                f"Failed to extract text from relatorio document: {session_data['url_relatorio']}"
            )

    # Extract voto text
    if session_data.get("url_voto"):
        voto_text = extract_document_text(session_data["url_voto"])
        if voto_text:
            session_data["conteudo_voto"] = voto_text
            logging.debug(f"Extracted {len(voto_text)} chars from voto document")
        else:
            logging.warning(
                f"Failed to extract text from voto document: {session_data['url_voto']}"
            )

    return session_data
