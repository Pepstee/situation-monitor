"""Allow ``python -m monitor`` to use the canonical CLI."""

from monitor.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
