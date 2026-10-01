"""Entry point: ``python -m autodiag`` / the ``autodiag`` console script."""

from autodiag import __version__


def main() -> None:
    from autodiag.ui.app import main as run_app

    raise SystemExit(run_app())


if __name__ == "__main__":
    print(f"AutoDiag Pro v{__version__}")
    main()
