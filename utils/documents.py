from io import BytesIO

import pdfplumber
from striprtf.striprtf import rtf_to_text
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import utils.dsl as dsl


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=5),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
def retry_document_download(and_link, link_type):
    """Retry document downloads with shorter backoff."""
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
