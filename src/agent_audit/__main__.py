"""Support ``python -m agent_audit`` as well as the ``agent-audit`` script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
