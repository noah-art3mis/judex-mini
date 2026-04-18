#!/usr/bin/env bash
# Export the five HC marimo notebooks to standalone HTML via
# `marimo export html`. The HTML embeds plotly.js + figure JSON
# directly, so charts stay fully interactive (hover / zoom / pan)
# offline — no server required.
#
# No extra deps: HTML export is built into marimo.
#
# Output lands under exports/html/ (gitignored).

set -euo pipefail

OUT_DIR="${OUT_DIR:-exports/html}"
mkdir -p "$OUT_DIR"

NOTEBOOKS=(
    hc_explorer
    hc_top_volume
    hc_famous_lawyers
    hc_admissibility
    hc_minister_archetypes
)

for nb in "${NOTEBOOKS[@]}"; do
    src="analysis/${nb}.py"
    dst="${OUT_DIR}/${nb}.html"
    if [[ ! -f "$src" ]]; then
        echo "SKIP  ${src} (not found)"
        continue
    fi
    echo "EXPORT  ${src} -> ${dst}"
    uv run marimo export html --force "$src" -o "$dst"
done

echo
echo "Done. HTMLs in ${OUT_DIR}/:"
ls -lh "$OUT_DIR"/*.html
