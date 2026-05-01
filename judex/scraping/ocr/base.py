"""Shared types for the OCR provider abstraction.

`ExtractResult` is the normalized output across providers — flat text
plus an opaque per-provider element list (Unstructured typed elements,
Mistral pages array, Chandra chunks). Downstream code depending on
the structure can branch on `provider`.

`OCRConfig` is the union of every provider's per-call options. Each
provider reads only the fields it needs; unused fields are inert.
The `api_key` defaults to `""` so cost/wall estimation call sites
can construct a valid config without hitting credentials.

`ProviderSpec` is each provider's self-description: the `extract`
callable plus metadata (cost model, wall anchor, env var, batch
support) the dispatcher and bakeoff harness need. Each provider
module exposes a module-level `SPEC: ProviderSpec` constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


@dataclass
class ExtractResult:
    text: str
    elements: Optional[list[dict[str, Any]]] = None
    pages_processed: Optional[int] = None
    provider: str = ""
    # Optional real cost in USD reported by the provider (Gemini computes
    # this from usageMetadata; Mistral / Modal-hosted providers leave it
    # None and the caller falls back to estimate_cost from PRICING).
    usd_cost: Optional[float] = None
    # Token counts for providers that bill by token (Gemini). Optional.
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class OCRConfig:
    provider: str
    api_key: str = ""
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


@dataclass(frozen=True)
class ProviderSpec:
    """Self-describing OCR provider.

    Each provider module exposes a module-level ``SPEC: ProviderSpec``
    constant; the dispatcher and bakeoff harness build their registry
    from these. Cost and wall functions take an :class:`OCRConfig` so
    the same union-of-options shape used at extract time also feeds
    metadata calls — providers read only the fields they care about.

    Fields:

    - ``name``: provider key (matches ``OCRConfig.provider``)
    - ``extract``: ``(pdf_bytes, *, config) -> ExtractResult``
    - ``cost``: ``(n_pages, config) -> USD`` for the price tier implied
      by ``config`` (e.g. Mistral batch vs sync, Unstructured strategy)
    - ``wall``: ``(n_pdfs, config) -> seconds`` for the wall-time anchor
      under that config; raise ``NotImplementedError`` for providers
      whose anchor has not been measured yet
    - ``env_var``: env-var name carrying the API key (``""`` for local
      providers and Modal-hosted providers that auth via Modal's token)
    - ``supports_batch``: whether this provider's cost/wall responds to
      ``config.batch=True`` (Mistral, Gemini); informational, used by
      the bakeoff harness to decide which configs to run
    """

    name: str
    extract: Callable[..., ExtractResult]
    cost: Callable[[int, OCRConfig], float]
    wall: Callable[[int, OCRConfig], float]
    env_var: str = ""
    supports_batch: bool = False
