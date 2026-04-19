"""Shared types for the OCR provider abstraction.

`ExtractResult` is the normalized output across providers — flat text
plus an opaque per-provider element list (Unstructured typed elements,
Mistral pages array, Chandra chunks). Downstream code depending on
the structure can branch on `provider`.

`OCRConfig` is the union of every provider's per-call options. Each
provider reads only the fields it needs; unused fields are inert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class ExtractResult:
    text: str
    elements: Optional[list[dict[str, Any]]] = None
    pages_processed: Optional[int] = None
    provider: str = ""


@dataclass
class OCRConfig:
    provider: str
    api_key: str
    api_url: Optional[str] = None
    languages: tuple[str, ...] = ("por",)
    timeout: int = 300

    # mistral
    model: str = "mistral-ocr-latest"
    batch: bool = False

    # unstructured
    strategy: str = "hi_res"

    # chandra
    mode: str = "accurate"
    output_format: str = "markdown"
    poll_interval: float = 2.0
    poll_max_wait: float = 600.0


class OCRProvider(Protocol):
    def extract(self, pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult: ...
