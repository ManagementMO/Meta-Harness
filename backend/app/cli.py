"""Meta-Harness CLI entry — ``meta-harness <subcommand>``.

Real subcommands land in BUILD_ORDER step (12). This stub exists so the
console_script in ``backend/pyproject.toml`` ([project.scripts]
``meta-harness = "app.cli:main"``) installs cleanly under ``uv sync``.
"""

import typer

app = typer.Typer(
    name="meta-harness",
    help="Meta-Harness — LangGraph-native substrate for self-improving agent harnesses.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show the Meta-Harness version."""
    from app import __version__
    typer.echo(f"meta-harness {__version__}")


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()
