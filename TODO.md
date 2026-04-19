## todo

- [ ] run analyses
    - [ ] check if new author info changes anything
    - [ ] add analysis segmentation by year or government
    - [ ] segmentation by primeiro autor x autores
- [ ] get more data
    - [ ] running tier 1 sweep
    - [x] get pdfs (HC 2026 andamento PDFs, running — 3,404/9,306 at 10:00)
- [ ] check golden example candidates
- [ ] check out tfidf clustering example
- confirm djes in the ground truth examples
- [ ] fix docs

### Document-universe follow-ups (from 2026-04-19 audit)

See [`docs/stf-portal.md § Document sources`](docs/stf-portal.md#document-sources--the-full-universe-of-pdfs--rtfs--voto-html)
and [`docs/current_progress.md`](docs/current_progress.md) for context.

- [ ] **Re-extract 2026 `sessao_virtual.documentos[].url` from
      cached JSON** (zero STF traffic; cache already has the URLs;
      625 cases → up to 1,302 new voto URLs). Use
      `scripts/renormalize_cases.py` scoped to the 2026 id range
      (`hc_calendar.year_to_id_range(2026)` → 267138..271138).
- [x] **Treat RTF as first-class in `peca_targets.py`.** Relaxed
      the `.pdf`-suffix filter via `_is_supported_doc_url` (accepts
      `.pdf`, `.rtf`, and STF's `?ext=RTF` query form). 372 RTF URLs
      now surface for 2026. Shipped 2026-04-19 with 393 unit tests
      green. *Follow-up still open*: pull `sessao_virtual.documentos[].url`
      into the target set (currently `pdf_targets` only walks
      `andamentos`).
- [x] **Rename `pdf` → `peca`** (matches STF's own `downloadPeca.asp`).
      Shipped 2026-04-19: modules (`peca_cli.py`, `peca_store.py`,
      `peca_targets.py`, `peca_cache.py`, `peca_utils.py`), scripts
      (`baixar_pecas.py`, `extrair_pecas.py`), Typer commands
      (`judex baixar-pecas` / `extrair-pecas`), classes (`PecaTarget`,
      `PecaStore`, `PecaAttemptRecord`), collector
      (`collect_peca_targets`). Sweep artifact filenames
      (`pdfs.state.json`, `pdfs.log.jsonl`, `pdfs.errors.jsonl`) and
      cache sidecars (`<sha1>.pdf.gz`) kept as-is — renaming mid-
      sweep would break the in-flight HC 2026 run and any monitoring
      tooling. Follow-up ticket for after the sweep finishes: rename
      the state/log/errors filenames + cache-sidecar extension.
- [x] **Add RTF branch to `extrair-pecas`.** Already in place:
      `src/utils/peca_utils.extract_document_text` detects PDF vs RTF
      by magic bytes and routes to `extract_rtf_text` (striprtf) or
      `extract_pdf_text_from_content` (pypdf). Sidecar label is
      `"rtf"` or `"pypdf_plain"`. No further code needed.
- [ ] **Second download sweep for voto PDFs** after re-extract
      lands. `sistemas.stf.jus.br` + `digital.stf.jus.br` are
      separate WAF counters from `portal.stf.jus.br`, so it can
      run concurrently with an andamento sweep if needed. Verify
      both hosts for WAF / 403 behavior on a small probe first
      (`digital.stf.jus.br` is unstudied).
- [ ] **Fix quadratic `_find_case_file` in `peca_targets.py`.**
      Today's sweep burned ~2 min of 99 %-CPU before the first HTTP
      because each CSV row does a full `rglob` over the 79k-file
      HC tree. Build a `{(classe, processo_id) → Path}` index once
      per root.
- [ ] **`CLAUDE.md` gotcha #5 is partly outdated.** Says "PDF URLs
      live on `sistemas.stf.jus.br`, not `portal.stf.jus.br`" —
      but every andamento URL in the 2026 corpus is
      `portal.stf.jus.br/processos/downloadPeca.asp`. The claim
      *is* correct for sessão-virtual voto PDFs. Tighten the
      wording.

## done

- [x] add warehouse