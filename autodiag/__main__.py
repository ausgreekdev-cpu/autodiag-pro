"""Entry point: ``python -m autodiag`` / the ``autodiag`` console script."""

import sys

from autodiag import __version__

_CLI_ARGS = {"ports", "doctor", "scan", "-h", "--help", "--version"}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in _CLI_ARGS:
        from autodiag.cli import main as cli_main

        raise SystemExit(cli_main(args))
    from autodiag.ui.app import main as run_app

    raise SystemExit(run_app())


if __name__ == "__main__":
    if not (len(sys.argv) > 1 and sys.argv[1] in _CLI_ARGS):
        print(f"AutoDiag Pro v{__version__}")
    main()
