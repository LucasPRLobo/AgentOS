"""Deprecated — OllamaProvider has moved to agentos.lm.providers.ollama.

This shim re-exports for backwards compatibility. Import from the new
location instead::

    from agentos.lm.providers.ollama import OllamaProvider
"""

import warnings

from agentos.lm.providers.ollama import OllamaProvider  # noqa: F401

warnings.warn(
    "Importing OllamaProvider from labos.providers.ollama is deprecated. "
    "Use 'from agentos.lm.providers.ollama import OllamaProvider' instead.",
    DeprecationWarning,
    stacklevel=2,
)
