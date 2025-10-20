# Judex-mini

# Instalação

```bash
# instalar wsl (SOMENTE WINDOWS)
wsl --install

# instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# instalar chromedriver (pode demorar)
sudo apt install chromium-chromedriver

# clonar repositório
git clone https://github.com/noah-art3mis/judex

# baixar dependências
cd judex && uv sync
```

## Uso

```BASH
# usar o CLI
uv run main.py
```

## Exemplos

```bash
# uso normal
uv run main.py --classe AI --processo-inicial 1234567 --processo-final 1234570

# abreviado (ver uv run main.py --help)
uv run main.py -c AI -i 1234567 -f 1234570

#custom output directory
uv run main.py -c AI -i 1234567 -f 1234570 --output-format json --output-dir results

# salvar arquivos no desktop do windows
uv run main.py --output-dir /mnt/c/Users/YourUsername/Desktop/judex-mini

# complete example
uv run main.py \
  --classe RE \
  --processo-inicial 1234567 \
  --processo-final 1234570 \
  --output-format json \
  --output-dir extracted_data \
  --log-level INFO
```
