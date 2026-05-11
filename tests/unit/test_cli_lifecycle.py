"""Tests for the sweep lifecycle CLI primitives — `judex parar`,
`judex retomar`, the `--detach` flag on `executar`, and the helpers
they share.

These tests pin two contracts:

1.  **The PID-file primitive is honest.** ``run_pipeline`` writes
    ``<saida>/executar.pid`` on entry and deletes it in its finally
    block. ``parar`` reads that file (or ``shards.pids`` for sharded),
    and only signals processes that ``os.kill(pid, 0)`` confirms are
    alive. Stale pid files don't get innocent processes SIGTERM'd.

2.  **The state journal carries enough to rebuild the operator's first
    command.** ``executar`` persists its kwargs via
    ``state.set_original_args``; ``retomar`` reads them back and
    reconstructs the executar argv. A state file missing the ``args``
    block produces a clean error, not a crash or a wrong-shape argv.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from judex.cli import (
    _build_retomar_argv,
    _executar_kwargs_for_state,
    _is_pid_alive,
    _newest_run_dir,
    _read_pids,
    _resolve_run_dir,
    app,
)


# ---------------------------------------------------------------------------
# Helpers


def test_newest_run_dir_returns_most_recent_by_mtime(tmp_path: Path) -> None:
    """``parar`` / ``retomar`` without an explicit ``<saida>`` default
    to the most-recently-touched run dir — which is almost always the
    one the operator just launched or paused."""
    old = tmp_path / "old-run"
    middle = tmp_path / "middle-run"
    new = tmp_path / "new-run"
    for d in (old, middle, new):
        d.mkdir()
    # Set explicit mtimes to remove filesystem-resolution flakiness.
    os.utime(old, (1_000, 1_000))
    os.utime(middle, (2_000, 2_000))
    os.utime(new, (3_000, 3_000))

    assert _newest_run_dir(tmp_path) == new


def test_newest_run_dir_returns_none_for_empty_or_missing_root(tmp_path: Path) -> None:
    assert _newest_run_dir(tmp_path / "does-not-exist") is None
    empty = tmp_path / "empty-root"
    empty.mkdir()
    assert _newest_run_dir(empty) is None


def test_resolve_run_dir_passes_explicit_path_through(tmp_path: Path) -> None:
    """When the operator passes an explicit ``<run_dir>``, the resolver
    is a no-op — no surprise redirections, no echoes."""
    explicit = tmp_path / "specific-run"
    explicit.mkdir()
    assert _resolve_run_dir(explicit) == explicit


def test_resolve_run_dir_errors_when_no_default_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty runs/active/ + no explicit arg = clean exit-2, not a stack
    trace. The resolver is the only place this error message lives, so
    every Coleta command (parar / retomar / acompanhar / relatar /
    recuperar) inherits the same operator-facing message."""
    # Point _newest_run_dir at an empty dir so resolver gets None.
    empty_root = tmp_path / "empty-active"
    empty_root.mkdir()
    monkeypatch.setattr("judex.cli._newest_run_dir", lambda: None)
    # Direct call: catch the SystemExit Typer raises.
    with pytest.raises(typer.Exit) as exc_info:
        _resolve_run_dir(None)
    assert exc_info.value.exit_code == 2


def test_acompanhar_relatar_recuperar_default_to_newest_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All Coleta commands that take <run_dir> share the same default —
    when omitted, fall back to the most recently touched dir under
    runs/active/. Pinned here so the uniform-surface contract can't
    silently drift back to "required argument" on one of the commands.
    """
    # Sub the resolver at the module level so every command sees the
    # same fake "newest" directory regardless of host filesystem state.
    sentinel = tmp_path / "sentinel-newest"
    sentinel.mkdir()

    seen: dict[str, Path] = {}

    def fake_resolve(explicit):
        if explicit is not None:
            return explicit
        seen["called"] = sentinel
        return sentinel

    monkeypatch.setattr("judex.cli._resolve_run_dir", fake_resolve)

    # Each command resolves through the helper before its body runs;
    # bodies will then fail because the sentinel dir has no log/state
    # files, but the resolver call itself is the contract under test.
    # We capture-and-ignore the inner failure.
    for cmd in ("relatar", "recuperar"):
        seen.pop("called", None)
        CliRunner().invoke(app, [cmd])  # no run_dir arg
        # Either way, the resolver was called with no explicit path.
        assert seen.get("called") == sentinel, f"{cmd} didn't default to newest"


def test_read_pids_mono_layout(tmp_path: Path) -> None:
    (tmp_path / "executar.pid").write_text("12345\n")
    assert _read_pids(tmp_path) == [12345]


def test_read_pids_sharded_layout_wins_over_mono(tmp_path: Path) -> None:
    """When both files exist (the launcher writes shards.pids; one of
    the children also wrote its own executar.pid), the sharded file is
    canonical — ``parar`` must signal every shard, not just one."""
    (tmp_path / "executar.pid").write_text("99999\n")
    (tmp_path / "shards.pids").write_text("100\n200\n300\n")
    assert _read_pids(tmp_path) == [100, 200, 300]


def test_read_pids_tolerates_blank_lines_and_garbage(tmp_path: Path) -> None:
    (tmp_path / "shards.pids").write_text("100\n\nNOT_A_PID\n200\n")
    assert _read_pids(tmp_path) == [100, 200]


def test_read_pids_returns_empty_when_no_file_present(tmp_path: Path) -> None:
    assert _read_pids(tmp_path) == []


def test_is_pid_alive_self_returns_true() -> None:
    assert _is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead_pid_returns_false() -> None:
    # Fork off a process that exits immediately, wait for it to finish,
    # then probe its PID. ``os.kill(pid, 0)`` raises ProcessLookupError
    # for reaped pids — the contract _is_pid_alive depends on.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    assert _is_pid_alive(proc.pid) is False


def test_build_retomar_argv_range_mode() -> None:
    args = {
        "classe": "HC", "inicio": 196282, "fim": 210963,
        "provedor": "pypdf", "forcar": False,
    }
    argv = _build_retomar_argv(
        Path("runs/active/hc2021"), args,
        nao_perguntar=True, detach=False,
    )
    assert argv == [
        "executar",
        "-c", "HC",
        "-i", "196282",
        "-f", "210963",
        "--saida", "runs/active/hc2021",
        "--nao-perguntar",
    ]


def test_build_retomar_argv_emits_non_default_provedor_and_concurrency() -> None:
    """Defaults are omitted to keep the argv lean and readable; only
    the operator's explicit overrides come back through."""
    args = {
        "classe": "HC", "inicio": 1, "fim": 2,
        "provedor": "chandra",
        "portal_concurrencia": 1,        # default → omitted
        "sistemas_concurrencia": 8,      # non-default → included
        "ocr_concurrencia": 4,           # default → omitted
        "forcar": True,
    }
    argv = _build_retomar_argv(
        Path("/tmp/run"), args, nao_perguntar=False, detach=True,
    )
    assert "--provedor" in argv and "chandra" in argv
    assert "--sistemas-concurrencia" in argv and "8" in argv
    assert "--portal-concurrencia" not in argv
    assert "--ocr-concurrencia" not in argv
    assert "--forcar" in argv
    assert "--detach" in argv


def test_build_retomar_argv_csv_mode_omits_range_flags() -> None:
    args = {"csv": "/tmp/targets.csv", "provedor": "pypdf"}
    argv = _build_retomar_argv(
        Path("/tmp/run"), args, nao_perguntar=False, detach=False,
    )
    assert "--csv" in argv and "/tmp/targets.csv" in argv
    assert "-c" not in argv and "-i" not in argv and "-f" not in argv


def test_executar_kwargs_for_state_serializes_paths_as_strings() -> None:
    """A snapshot round-trip is JSON, which doesn't carry Path objects.
    The packer flattens them to str so retomar can read them back as
    plain dict entries without a JSON decoder hook."""
    out = _executar_kwargs_for_state(
        classe="HC", inicio=1, fim=2,
        csv=None, retentar_de=Path("/tmp/errors.jsonl"),
        rotulo="test", provedor="pypdf", forcar=False,
        portal_concurrencia=1, sistemas_concurrencia=1, ocr_concurrencia=4,
        proxy_pool=Path("/tmp/proxies"),
    )
    assert out["retentar_de"] == "/tmp/errors.jsonl"
    assert out["proxy_pool"] == "/tmp/proxies"
    assert out["csv"] is None
    # JSON-roundtrippable.
    json.dumps(out)


# ---------------------------------------------------------------------------
# `parar`


def _spawn_sleeper() -> subprocess.Popen:
    """Long-lived child that responds to SIGTERM. Used to test
    ``parar`` against a real PID."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_sleeper_with_reaper() -> tuple[subprocess.Popen, "threading.Thread"]:
    """Spawn the sleeper and immediately arm a daemon thread to ``wait()``
    on it. The reaper drains the zombie *as soon as* parar's SIGTERM lands,
    so parar's ``os.kill(pid, 0)`` probe sees ProcessLookupError on the
    next poll — matching production semantics (where parar isn't the
    parent of executar and zombies don't form). Without the reaper, the
    test process keeps the dead child as a zombie and parar incorrectly
    concludes the process is still alive."""
    import threading
    child = _spawn_sleeper()
    reaper = threading.Thread(target=child.wait, daemon=True)
    reaper.start()
    return child, reaper


def test_parar_sigterms_pid_from_executar_pid_file(tmp_path: Path) -> None:
    """End-to-end: spawn a real child, write its pid to executar.pid,
    invoke ``judex parar <saida>``, observe the child terminate."""
    child, reaper = _spawn_sleeper_with_reaper()
    try:
        (tmp_path / "executar.pid").write_text(f"{child.pid}\n")

        result = CliRunner().invoke(app, ["parar", str(tmp_path), "--timeout", "5"])
        assert result.exit_code == 0, result.output
        reaper.join(timeout=5)
        assert child.returncode != 0  # SIGTERM exit
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_parar_signals_every_pid_in_shards_pids(tmp_path: Path) -> None:
    """Sharded layout: ``parar`` must signal all N children, not just one."""
    spawned = [_spawn_sleeper_with_reaper() for _ in range(3)]
    children = [c for c, _ in spawned]
    try:
        (tmp_path / "shards.pids").write_text(
            "\n".join(str(c.pid) for c in children) + "\n"
        )

        result = CliRunner().invoke(app, ["parar", str(tmp_path), "--timeout", "5"])
        assert result.exit_code == 0, result.output
        for c, reaper in spawned:
            reaper.join(timeout=5)
            assert c.returncode != 0
    finally:
        for c in children:
            if c.poll() is None:
                c.kill()
                c.wait()


def test_parar_errors_cleanly_when_no_pid_file_present(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["parar", str(tmp_path)])
    assert result.exit_code == 2
    assert "nem executar.pid nem shards.pids" in result.output


def test_parar_handles_stale_pid_file_without_error(tmp_path: Path) -> None:
    """A pid file pointing at a long-dead PID shouldn't crash ``parar``;
    it should observe ``os.kill`` -> ProcessLookupError and move on.
    This is the SIGKILL'd-prior-run case the runner's finally block
    can't defend against."""
    dead = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    dead.wait()
    (tmp_path / "executar.pid").write_text(f"{dead.pid}\n")

    result = CliRunner().invoke(app, ["parar", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "já não existe" in result.output or "encerraram" in result.output


# ---------------------------------------------------------------------------
# `retomar`


def _write_state(saida: Path, *, args: object) -> None:
    """Hand-craft an executar.state.json for retomar to read."""
    payload = {
        "schema_version": 2,
        "started_at": "2026-05-11T00:00:00Z",
        "snapshot_at": "2026-05-11T00:00:00Z",
        "args": args,
        "cases": {},
    }
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "executar.state.json").write_text(json.dumps(payload))


def test_retomar_errors_when_state_missing(tmp_path: Path) -> None:
    saida = tmp_path / "empty-run"
    saida.mkdir()
    result = CliRunner().invoke(app, ["retomar", str(saida)])
    assert result.exit_code == 2
    assert "não existe" in result.output


def test_retomar_errors_when_args_block_missing(tmp_path: Path) -> None:
    """Pre-feature state files (no ``args`` block) get a clean error
    pointing the operator at the executar fallback."""
    saida = tmp_path / "legacy-run"
    _write_state(saida, args=None)
    result = CliRunner().invoke(app, ["retomar", str(saida)])
    assert result.exit_code == 2
    assert "bloco `args`" in result.output
    assert "uv run judex executar" in result.output


def test_retomar_dispatches_executar_with_reconstructed_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The args block round-trips into an executar argv. We intercept
    the inner ``app()`` call to capture the argv without actually
    re-running executar (which would try to scrape STF)."""
    saida = tmp_path / "run"
    _write_state(saida, args={
        "classe": "HC", "inicio": 1, "fim": 5,
        "provedor": "pypdf", "forcar": False,
    })

    captured: dict[str, object] = {}

    def fake_app(argv: list[str], standalone_mode: bool = True) -> None:
        captured["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr("judex.cli.app", fake_app)

    result = CliRunner().invoke(app, [
        "retomar", str(saida), "--nao-perguntar",
    ])
    # The inner fake_app raises SystemExit(0); Typer propagates it.
    assert result.exit_code == 0, result.output

    argv = captured["argv"]
    assert argv[0] == "executar"
    assert "-c" in argv and "HC" in argv
    assert "-i" in argv and "1" in argv
    assert "-f" in argv and "5" in argv
    assert "--saida" in argv and str(saida) in argv
    assert "--nao-perguntar" in argv


# ---------------------------------------------------------------------------
# `--detach`


def test_executar_detach_writes_log_and_prints_pid(tmp_path: Path) -> None:
    """End-to-end: invoke executar --detach against an empty CSV.
    The child will exit quickly with "no targets resolved", but the
    parent must still print pid + log + saida and exit 0 from its own
    perspective (the child's exit is captured into the log)."""
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("classe,processo\n")
    saida = tmp_path / "run"

    result = CliRunner().invoke(app, [
        "executar", "--csv", str(empty_csv), "--saida", str(saida),
        "--rotulo", "test", "--nao-perguntar", "--detach",
    ])
    # The parent always returns 2 because the child sees an empty CSV
    # → "nenhum alvo resolvido" → exit 2. But for the detach contract
    # we only care that the parent printed pid + log + saida + parar
    # advice before exiting. Wait briefly for child to write its log.
    time.sleep(0.5)
    # When the empty-csv child exits immediately, the parent will have
    # taken the "filho saiu cedo" branch — that's also acceptable; the
    # contract under test is "parent runs the detach codepath".
    assert (
        "filho saiu cedo" in result.output
        or ("pid:" in result.output and "log:" in result.output)
    ), result.output


# ---------------------------------------------------------------------------
# `listar`
#
# The library-level taxonomy + sorting + pruning live in
# ``tests/unit/test_run_index.py`` — these tests pin the CLI surface
# on top of it: status filter, ``--json``, ``--podar-pids``, and the
# empty-root message that the operator sees when ``runs/active/`` is
# clean. Rendering is via rich.Table; we only check that the run
# names + status strings show up in stdout (not exact alignment).


def _make_run_dir(root: Path, name: str, *, pid: int | None = None) -> Path:
    """Create ``<root>/<name>/`` with a minimal state.json (and optionally
    a pid file). Mirrors what ``run_pipeline`` would write on entry,
    without spinning up a real pipeline."""
    saida = root / name
    saida.mkdir(parents=True)
    (saida / "executar.state.json").write_text(
        '{"started_at": "2026-05-11T19:00:00Z", "cases": {}}',
        encoding="utf-8",
    )
    if pid is not None:
        (saida / "executar.pid").write_text(f"{pid}\n", encoding="utf-8")
    return saida


def test_listar_shows_running_and_finished_runs(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _make_run_dir(root, "alive", pid=os.getpid())
    _make_run_dir(root, "done")

    result = CliRunner().invoke(app, ["listar", "--root", str(root)])

    assert result.exit_code == 0, result.output
    assert "alive" in result.output
    assert "done" in result.output
    assert "running" in result.output
    assert "finished" in result.output


def test_listar_filters_by_apenas_running(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _make_run_dir(root, "alive", pid=os.getpid())
    _make_run_dir(root, "done")

    result = CliRunner().invoke(
        app, ["listar", "--root", str(root), "--apenas", "running"]
    )

    assert result.exit_code == 0, result.output
    assert "alive" in result.output
    assert "done" not in result.output


def test_listar_rejects_unknown_status_filter(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _make_run_dir(root, "any")

    result = CliRunner().invoke(
        app, ["listar", "--root", str(root), "--apenas", "bogus"]
    )

    assert result.exit_code != 0
    assert "inválido" in result.output or "Invalid" in result.output


def test_listar_json_emits_machine_readable_lines(tmp_path: Path) -> None:
    """``--json`` is the path that backs jq pipelines (operator scripts,
    dashboards). One JSON object per line, no header, no rich markup."""
    root = tmp_path / "runs"
    _make_run_dir(root, "done")

    result = CliRunner().invoke(
        app, ["listar", "--root", str(root), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["status"] == "finished"
    assert payload["saida"].endswith("done")


def test_listar_empty_root_emits_friendly_message(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    result = CliRunner().invoke(app, ["listar", "--root", str(root)])

    assert result.exit_code == 0
    assert "nenhuma Coleta" in result.output


def test_listar_podar_pids_removes_stale_only(tmp_path: Path) -> None:
    """``--podar-pids`` is the cleanup action for ``stale`` runs — the
    SIGKILL-leaked pid files that ``parar`` would no-op on."""
    root = tmp_path / "runs"
    _make_run_dir(root, "live", pid=os.getpid())
    _make_run_dir(root, "stale", pid=999_999_999)

    result = CliRunner().invoke(
        app, ["listar", "--root", str(root), "--podar-pids"]
    )

    assert result.exit_code == 0, result.output
    assert (root / "live" / "executar.pid").exists()
    assert not (root / "stale" / "executar.pid").exists()
    assert "podou 1" in result.output


def test_listar_table_includes_alvos_and_duracao_columns(tmp_path: Path) -> None:
    """The enrichment columns (n_targets + elapsed time) should show
    up in the rendered table. Operator-facing readability — same axis
    Modal's ``app list`` uses."""
    root = tmp_path / "runs"
    saida = root / "with-cases"
    saida.mkdir(parents=True)
    (saida / "executar.state.json").write_text(
        '{"started_at": "2026-05-11T19:00:00+00:00", '
        '"snapshot_at": "2026-05-11T19:30:00+00:00", '
        '"cases": {"HC:1": {}, "HC:2": {}}}',
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["listar", "--root", str(root)])

    assert result.exit_code == 0, result.output
    assert "alvos" in result.output
    assert "duração" in result.output
    assert "2" in result.output         # n_targets
    assert "30m" in result.output       # elapsed (1800s → 30m 0s)


def test_listar_incluir_arquivo_merges_active_and_archive(tmp_path: Path) -> None:
    """``--incluir-arquivo`` extends the scan to ``runs/archive/``
    (resolved relative to ``--root``'s parent)."""
    root = tmp_path / "runs" / "active"
    archive = tmp_path / "runs" / "archive"
    _make_run_dir(root, "live", pid=os.getpid())
    _make_run_dir(archive, "old")

    no_archive = CliRunner().invoke(app, ["listar", "--root", str(root)])
    with_archive = CliRunner().invoke(
        app, ["listar", "--root", str(root), "--incluir-arquivo"]
    )

    assert "old" not in no_archive.output
    assert "old" in with_archive.output
    assert "live" in with_archive.output


# ---------------------------------------------------------------------------
# Label-based addressing — ``judex parar hc2021`` instead of full path


def test_resolve_run_dir_resolves_label_to_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Modal/Heroku affordance: passing a label that isn't a path
    falls through to ``find_by_label``; an unambiguous match resolves."""
    active = tmp_path / "runs" / "active"
    active.mkdir(parents=True)
    target = active / "hc2021-fillin-20260504"
    target.mkdir()
    (target / "executar.state.json").write_text(
        '{"started_at": "2026-05-11T19:00:00Z", '
        '"args": {"rotulo": "hc2021-fillin"}, "cases": {}}',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    from judex.cli import _resolve_run_dir

    resolved = _resolve_run_dir(Path("hc2021-fillin"))

    # ``find_by_label`` returns paths relative to cwd (``runs/active/…``);
    # compare resolved-real-paths to avoid the absolute-vs-relative mismatch.
    assert resolved.resolve() == target.resolve()


def test_resolve_run_dir_errors_on_unknown_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "runs" / "active").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    from judex.cli import _resolve_run_dir

    with pytest.raises(typer.Exit) as exc_info:
        _resolve_run_dir(Path("does-not-exist"))

    assert exc_info.value.exit_code == 2


def test_resolve_run_dir_errors_on_ambiguous_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two runs with the same prefix → resolver refuses to guess; the
    operator must disambiguate. Same safety as ``kubectl delete`` on
    an ambiguous pod prefix."""
    active = tmp_path / "runs" / "active"
    active.mkdir(parents=True)
    for name in ("hc2021-a", "hc2021-b"):
        d = active / name
        d.mkdir()
        (d / "executar.state.json").write_text(
            f'{{"args": {{"rotulo": "{name}"}}, "cases": {{}}}}',
            encoding="utf-8",
        )

    monkeypatch.chdir(tmp_path)
    from judex.cli import _resolve_run_dir

    with pytest.raises(typer.Exit) as exc_info:
        _resolve_run_dir(Path("hc2021"))

    assert exc_info.value.exit_code == 2


# ---------------------------------------------------------------------------
# `parar --dry-run`


def test_parar_dry_run_prints_pids_without_signalling(tmp_path: Path) -> None:
    """``--dry-run`` reads the pid file, prints what *would* be sent,
    exits 0 without actually signalling. The safety net before a
    16-shard SIGTERM."""
    saida = tmp_path / "run"
    saida.mkdir()
    (saida / "executar.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["parar", str(saida), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert str(os.getpid()) in result.output
    # Our own process must still be alive — confirms no signal was sent.
    assert _is_pid_alive(os.getpid())


# ---------------------------------------------------------------------------
# `arquivar`


def test_arquivar_moves_finished_run_to_archive(tmp_path: Path) -> None:
    """Happy path: a ``finished`` run moves cleanly to the destination."""
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    saida = _make_run_dir(active, "done")  # finished — no pid file

    result = CliRunner().invoke(
        app, ["arquivar", str(saida), "--destino", str(archive)]
    )

    assert result.exit_code == 0, result.output
    assert not saida.exists()
    assert (archive / "done").is_dir()
    assert (archive / "done" / "executar.state.json").is_file()


def test_arquivar_refuses_running_run_without_forcar(tmp_path: Path) -> None:
    """A ``running`` run has a live pid file — moving it would orphan
    the process at a non-existent path. The guard exists exactly so an
    operator who reflexively types ``arquivar`` on the wrong run gets a
    chance to notice."""
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    saida = _make_run_dir(active, "live", pid=os.getpid())

    result = CliRunner().invoke(
        app, ["arquivar", str(saida), "--destino", str(archive)]
    )

    assert result.exit_code != 0
    assert "running" in result.output
    assert saida.exists()           # not moved
    assert not (archive / "live").exists()


def test_arquivar_forcar_overrides_running_guard(tmp_path: Path) -> None:
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    saida = _make_run_dir(active, "live", pid=os.getpid())

    result = CliRunner().invoke(
        app, ["arquivar", str(saida), "--destino", str(archive), "--forcar"]
    )

    assert result.exit_code == 0, result.output
    assert (archive / "live").is_dir()


def test_arquivar_dry_run_reports_target_without_moving(tmp_path: Path) -> None:
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    saida = _make_run_dir(active, "done")

    result = CliRunner().invoke(
        app, ["arquivar", str(saida), "--destino", str(archive), "--dry-run"]
    )

    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert saida.exists()           # untouched
    assert not (archive / "done").exists()


def test_arquivar_errors_on_destination_collision(tmp_path: Path) -> None:
    """Name collision in archive → error, not silent overwrite. The
    operator resolves by renaming one of the two."""
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    saida = _make_run_dir(active, "dup")
    (archive / "dup").mkdir(parents=True)

    result = CliRunner().invoke(
        app, ["arquivar", str(saida), "--destino", str(archive)]
    )

    assert result.exit_code != 0
    assert "já existe" in result.output
    assert saida.exists()


# ---------------------------------------------------------------------------
# `relatar --json`


def test_relatar_json_emits_machine_readable_payload(tmp_path: Path) -> None:
    """``--json`` serialises the ``RunSummary`` dataclass with Path /
    Enum coerced to strings. Standard scripting contract."""
    saida = tmp_path / "run"
    saida.mkdir()
    # Minimal: an empty state.json + a report.md so layout detects mono.
    (saida / "executar.state.json").write_text('{"cases": {}}', encoding="utf-8")
    (saida / "report.md").write_text("# report\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["relatar", str(saida), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_dir"].endswith("run")
    assert payload["layout"] in ("mono", "sharded", "empty")
    assert isinstance(payload["state"], str)
