"""Internal GitHub integration implementation package.

Use submodule imports from ``bumpkin.integrations.github.*`` within the codebase.
The legacy ``bumpkin.github`` compatibility shim still exists for external
callers, but new internal imports should not route through it.
"""

__all__: list[str] = []
