"""PaddleOCR client — calls the Modal-hosted endpoint.

**Disqualified** for Portuguese legal text (2026-04-30 bakeoff,
see docs/reports/2026-04-30-ocr-bakeoff.md). 7.26% median CER looks
acceptable but the median averages over the readable portion — Paddle
has documented catastrophic per-line failures on 3 of 6 sampled docs:

- Strips ALL Portuguese diacritics (``questão`` → ``questao``,
  ``GOIÁS`` → ``GOIAS``, ``hipótese`` → ``hip6tese`` with literal ``6``).
- Whole-line OCR collapse (e.g. ``r ezuooae oru asaadoy e 'aoiqg
  opuaja opoiadns anb epudv``) embedded in otherwise readable text.
- Substantive clauses silently dropped on ``8e11f096`` (`afirmam não
  subsistir interesse...`), ``04dff48e`` (`cujos atos estejam sujeitos
  diretamente...`), ``16f4709e`` (`Remeta-se cópia...`).
- Letter↔digit substitutions: ``O → 0``, ``ó → 6``, ``Nº → N9``.

Failure mode is invisible to length checks and CER averages but
corrupts streaming NLP. Do not use in production.
"""

from __future__ import annotations

from judex.scraping.ocr._modal_client import call_modal
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    return call_modal("paddle_extract", pdf_bytes, provider="paddle")


def cost(n_pages: int, config: OCRConfig) -> float:
    # Modal-hosted on a10 — placeholder per 2026-04-30 cost research.
    # Real $/1k must come from Modal billing aggregated post-run.
    return n_pages * 0.080 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    # Anchor pending — first bakeoff against the Modal endpoint will set this.
    raise NotImplementedError(
        "paddle wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="paddle",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
