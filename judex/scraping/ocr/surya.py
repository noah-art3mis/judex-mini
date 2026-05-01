"""Surya OCR client — calls the Modal-hosted endpoint.

Bakeoff result (2026-04-30, see docs/reports/2026-04-30-ocr-bakeoff.md):
3.62% median CER, $0.18/1k pages. Correct reading order between phrases
but several distinct downstream burdens. Pinned to ``surya-ocr==0.16.7
+ transformers==4.56.1`` — 0.17 has a self-inconsistency bug in
``SuryaDecoderModel`` ↔ ``SuryaDecoderConfig.pad_token_id``.

Known issues (downstream parsing burden):
- Persistent rich-text injection: ``<b>...</b>``, ``<math>N^{\\circ}</math>``.
- Word-shuffle within multi-line phrases (e.g. ``REMESSA DOS AUTOS AO
  TRIBUNAL COMPETENTE`` → ``Remessa / TRIBUNAL / DOS / AUTOS / AO /
  COMPETENTE``).
- Glyph homoglyphs: Greek ``Ε`` (U+0395) for Latin ``E``, U+2116 ``№``
  for ``Nº`` — visually identical, breaks UTF-8 equality and search.
- Investigate ``output_format="text"`` flag before keeping in production.
"""

from __future__ import annotations

from judex.scraping.ocr._modal_client import call_modal
from judex.scraping.ocr.base import ExtractResult, OCRConfig, ProviderSpec


def extract(pdf_bytes: bytes, *, config: OCRConfig) -> ExtractResult:
    return call_modal("surya_extract", pdf_bytes, provider="surya")


def cost(n_pages: int, config: OCRConfig) -> float:
    # Modal-hosted on l40s — placeholder per 2026-04-30 cost research.
    return n_pages * 0.180 / 1000


def wall(n_pdfs: int, config: OCRConfig) -> float:
    raise NotImplementedError(
        "surya wall anchor pending; refresh from the next OCR bakeoff"
    )


SPEC = ProviderSpec(
    name="surya",
    extract=extract,
    cost=cost,
    wall=wall,
    env_var="",
    supports_batch=False,
)
