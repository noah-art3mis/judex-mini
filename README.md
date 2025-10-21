# judex-mini

Extração automatizada de dados de processos do STF.

# Instalação

```bash
# instalar wsl (SOMENTE WINDOWS)
wsl --install

# instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# instalar chromedriver (pode demorar)
sudo apt install chromium-chromedriver

# clonar repositório
git clone https://github.com/noah-art3mis/judex-mini

# baixar dependências
cd judex-mini && uv sync
```

## Uso

```bash
# uso normal
uv run main.py --classe ADI --processo-inicial 1 --processo-final 2

# abreviado (ver uv run main.py --help)
uv run main.py -c AI -i 1234567 -f 1234570

# salvar arquivos no desktop do windows
uv run main.py --output-dir /mnt/c/Users/YourUsername/Desktop/judex-mini
```

Para mais detalhes ver `uv run main.py --help`. Para alterar valores (max_retries, webdrivre_timeout, ver `config.py`)

Para testar:

```bash
# usa o processo padrão (AI 772309), output em json, salva em cima do arquivo
# checar manualmente se corresponde ao arquivo extraído manualmente (tests/ground_truth/AI_772309.json)
uv run main.py --overwrite

# teste automatico com processo customizado
# requer que haja um arquivo equivalente em tests/ground_truth/RE_1234567.json
uv run main.py -c RE -i 1234567 -f 1234567 --test
```

## Repository Documentation

Usa: selenium (scraping), beautifulsoup4 (html parsing), tenacity (retry), typer (CLI)

## File Structure

### Core Application Files

-   **`main.py`** - CLI entry point using Typer.
-   **`src/scraper.py`** - Main scraping logic.
-   **`src/config.py`** - Standard configuration

### Data Layer (`src/data/`)

-   **`types.py`** - Defines the `StfItem` TypedDict structure.
-   **`export.py`** - Handles data export functionality (JSON/CSV formats).
-   **`output.py`** - Configuration for output formatting.

### Extraction Module (`src/extraction/`)

-   **`extract_*.py`** - Individual extraction functions for specific data fields.

### Utilities (`src/utils/`)

-   **`driver.py`** - Selenium WebDriver management with retry logic
-   **`get_element.py`** - Element finding utilities
-   **`text_utils.py`** - Text processing and normalization
-   **`timing.py`** - Performance timing utilities
-   **`validation.py`** - Data validation functions

### Testing (`src/testing/` & `tests/`)

-   **`src/testing/ground_truth_test.py`** - Automated testing against known good data
-   **`tests/ground_truth/`** - Contains reference JSON files for testing:
    -   `AI_772309.json` - AI case reference data
    -   `MI_12.json` - MI case reference data
    -   `RE_1234567.json` - RE case reference data

### Configuration & Dependencies

-   **`pyproject.toml`** - Project configuration
-   **`uv.lock`** - Dependency lock file

## Issues

-   Lacks fault tolerance -- can corrupt data opening the same file at the same time
-   recreates driver every time
-   crashes if there is not enough disk space
-   no progressive backoff for 403s
