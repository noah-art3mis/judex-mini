from io import BytesIO
from typing import Optional

import pdfplumber
from striprtf.striprtf import rtf_to_text
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import src.dsl as dsl
from src.config import ScraperConfig


def create_document_retry_decorator(config: ScraperConfig):
    """Create retry decorator for document operations with configurable parameters."""
    return retry(
        stop=stop_after_attempt(config.document_max_retries),
        wait=wait_exponential(
            multiplier=config.document_backoff_multiplier,
            min=config.document_backoff_min,
            max=config.document_backoff_max,
        ),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )


def retry_document_download(
    and_link, link_type, config: Optional[ScraperConfig] = None
):
    """Retry document downloads with shorter backoff."""
    if config is None:
        config = ScraperConfig()

    # Create retry decorator with config
    retry_decorator = create_document_retry_decorator(config)

    @retry_decorator
    def _retry_download():
        if and_link == "NA":
            return "NA"

        if ".pdf" in and_link:
            response = dsl.get_response(and_link)
            file_like = BytesIO(response.content)
            content = ""
            with pdfplumber.open(file_like) as pdf:
                for pagina in pdf.pages:
                    content += pagina.extract_text() + "\n"
            return content
        elif "RTF" in and_link:
            response = dsl.get_response(and_link)
            return rtf_to_text(response.text)
        else:
            return dsl.get(and_link)

    return _retry_download()
