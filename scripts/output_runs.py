"""Stage derived outputs; publish after success and preserve any previous run.

Single implementation lives in verify2026_outputs (bounded Windows-lock retries,
completed staging kept after a publication failure). This module re-exports it
so every stage uses the same publication behaviour.
"""
from verify2026_outputs import PublicationError, check_destination, publish_stage, staged_output

__all__ = ['PublicationError', 'check_destination', 'publish_stage', 'staged_output']
