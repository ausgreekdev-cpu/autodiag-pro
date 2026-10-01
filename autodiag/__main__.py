"""Entry point: ``python -m autodiag`` / the ``autodiag`` console script."""

from autodiag import __version__


def main() -> None:
    print(f"AutoDiag Pro v{__version__} — OBD-II scan tool")


if __name__ == "__main__":
    main()
