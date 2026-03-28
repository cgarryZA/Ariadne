"""Tool registration orchestrator — imports all tool modules and registers them."""

from tools import (
    analysis,
    classification,
    discovery,
    export,
    library,
    monitoring,
    reading,
    screening,
    setup,
    writing,
)

_MODULES = [
    setup,
    discovery,
    library,
    screening,
    analysis,
    reading,
    classification,
    writing,
    monitoring,
    export,
]


def register_all(mcp):
    """Register all tool modules with the given FastMCP instance."""
    for module in _MODULES:
        module.register(mcp)
