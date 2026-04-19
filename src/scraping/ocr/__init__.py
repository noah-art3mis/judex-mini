"""Unified OCR provider abstraction over Unstructured / Mistral / Chandra.

Use `extract_pdf(pdf_bytes, config=OCRConfig(provider="mistral", api_key=...))`
as the single entry point. For Mistral batch (50 % cost reduction,
~24 h turnaround), see `src.scraping.ocr.mistral.{build_batch_jsonl,
submit_batch, wait_for_batch, download_batch_output, parse_batch_results}`.

Cost gating: `estimate_cost("mistral", 64603 * 5, batch=True)` returns
USD before you launch a sweep.
"""

from src.scraping.ocr.base import ExtractResult, OCRConfig, OCRProvider
from src.scraping.ocr.dispatch import (
    PRICING,
    cheapest_provider,
    estimate_cost,
    extract_pdf,
)

__all__ = [
    "ExtractResult",
    "OCRConfig",
    "OCRProvider",
    "PRICING",
    "cheapest_provider",
    "estimate_cost",
    "extract_pdf",
]
