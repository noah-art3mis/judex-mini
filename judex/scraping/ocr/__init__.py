"""Unified OCR provider abstraction over Unstructured / Mistral / Chandra /
Gemini / Modal-hosted (Tesseract / Surya / PaddleOCR) plus the local
pypdf text-layer reader.

Use ``extract_pdf(pdf_bytes, config=OCRConfig(provider="mistral", api_key=...))``
as the single entry point. For Mistral batch (50 % cost reduction,
~24 h turnaround), see ``judex.scraping.ocr.mistral.{build_batch_jsonl,
submit_batch, wait_for_batch, download_batch_output, parse_batch_results}``.

Each provider self-describes via a module-level ``SPEC: ProviderSpec``;
the registry in ``dispatch`` is built from those. Cost gating example:
``estimate_cost("mistral", 64603 * 5, batch=True)`` returns USD before
you launch a sweep.
"""

from judex.scraping.ocr.base import (
    ExtractResult,
    OCRConfig,
    OCRProvider,
    ProviderSpec,
)
from judex.scraping.ocr.dispatch import (
    REGISTRY,
    cheapest_provider,
    estimate_cost,
    estimate_wall,
    extract_pdf,
    get_provider,
)

__all__ = [
    "ExtractResult",
    "OCRConfig",
    "OCRProvider",
    "ProviderSpec",
    "REGISTRY",
    "cheapest_provider",
    "estimate_cost",
    "estimate_wall",
    "extract_pdf",
    "get_provider",
]
