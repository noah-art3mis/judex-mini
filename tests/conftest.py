"""Test-suite-wide fixtures.

Currently only one concern: ``judex/cli.py`` calls ``load_dotenv()`` at
module import so the CLI picks up operator-specific paid-infra config
(``FLY_TESSERACT_URL``, ``JUDEX_AUTO_TESSERACT_PROVIDER``, API keys).
That import inevitably happens during pytest collection (anything that
imports ``judex.*`` may transitively pull in ``judex.cli``), and once
``os.environ`` is populated from ``.env`` it stays populated for the
rest of the process.

Tests must not see operator-specific defaults — they're brittle
otherwise, and break on whichever machine the test is run on. The
fixture below strips the env vars whose unset-vs-set state is observed
by code under test (currently just ``JUDEX_AUTO_TESSERACT_PROVIDER`` —
the others are read inside provider modules that tests already mock).
Tests that *want* to set them should use ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os

import pytest


_OPERATOR_ENV_VARS = (
    # judex/sweeps/extrair_pecas.pick_provider observes this; default is
    # `tesseract` if unset, but the operator's .env may carry
    # `tesseract_fly` for production scale-out — which would skew tests
    # that pin the default routing.
    "JUDEX_AUTO_TESSERACT_PROVIDER",
)


@pytest.fixture(autouse=True)
def _isolate_operator_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip operator-leaking env vars before every test.

    Tests that need a specific value should use ``monkeypatch.setenv``
    explicitly. Autouse so no test has to remember.
    """
    for name in _OPERATOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
