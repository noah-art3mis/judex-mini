"""judex-mini entry-point shim.

The CLI implementation lives in ``src/cli.py`` so it can be editable-
installed by ``uv sync`` (and picked up by the ``judex`` console
script wired via ``[project.scripts]`` in ``pyproject.toml``). This
file keeps ``uv run python main.py …`` working as an alias.
"""

from judex.cli import app


if __name__ == "__main__":
    app()
