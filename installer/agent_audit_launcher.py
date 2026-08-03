"""PyInstaller entry point for the Windows build.

PyInstaller freezes a *script*. agent-audit's console entry point is a module
function (``agent-audit = "agent_audit.cli:main"`` in pyproject.toml), which pip
turns into a generated shim at install time — there is no file on disk to point
PyInstaller at. This is that file, and it does nothing else.

Note the naming split the rest of the port has to keep straight: the *command*
is ``agent-audit`` (hyphen) and the *module* is ``agent_audit`` (underscore).
"""

from __future__ import annotations

import sys

from agent_audit.cli import main

if __name__ == "__main__":
    sys.exit(main())
