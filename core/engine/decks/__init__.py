"""Decks engine — generate PPTX from a brand template + a structured spec.

See ``core/conventions/deck-template.md`` for the convention this engine
implements: template storage outside the repo, per-seat ``decks.yaml``
config, **real-layout discovery** (address the template's actual layouts
by index/name and placeholders by idx — no layout-rename convention), and
the spec schema.
"""

from .builder import (
    BuildError,
    BuildReport,
    build_from_spec,
    load_spec,
    resolve_spec_template,
)
from .config import DecksConfig, DecksConfigError, load_decks_config
from .validate import (
    LayoutInfo,
    PlaceholderInfo,
    SpecValidationResult,
    catalog_template,
    validate_spec,
)

__all__ = [
    "BuildError",
    "BuildReport",
    "DecksConfig",
    "DecksConfigError",
    "LayoutInfo",
    "PlaceholderInfo",
    "SpecValidationResult",
    "build_from_spec",
    "catalog_template",
    "load_decks_config",
    "load_spec",
    "resolve_spec_template",
    "validate_spec",
]
