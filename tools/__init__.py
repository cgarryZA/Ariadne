"""Tool registration orchestrator — imports all tool modules and registers them."""

from tools import (
    analysis,
    classification,
    concepts,
    discovery,
    export,
    latex,
    library,
    monitoring,
    network,
    reading,
    screening,
    setup,
    synthesis,
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
    synthesis,
    concepts,
    network,
    latex,
    writing,
    monitoring,
    export,
]


def register_all(mcp):
    """Register all tool modules with the given FastMCP instance."""
    for module in _MODULES:
        module.register(mcp)
