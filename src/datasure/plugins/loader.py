"""
Plugin discovery and loading.

Two sources are checked in order:
  1. Python package entry_points (group: datasure.validators)
  2. Local .py files in the configured plugins_dir directory
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datasure.validators.base import BaseValidator

log = logging.getLogger(__name__)


def load_plugins(registry: dict[str, type], plugins_dir: Path | None = None) -> None:
    """Discover and register all available plugins into `registry`."""
    _load_entry_point_plugins(registry)
    if plugins_dir:
        _load_local_plugins(registry, Path(plugins_dir))


def _load_entry_point_plugins(registry: dict[str, type]) -> None:
    try:
        eps = importlib.metadata.entry_points(group="datasure.validators")
    except Exception:
        return
    for ep in eps:
        try:
            cls = ep.load()
            if _is_valid_plugin(cls):
                registry[cls.name] = cls
                log.info("Plugin loaded from entry point '%s': %s", ep.name, cls.name)
        except Exception:
            log.exception("Failed to load plugin from entry point '%s'", ep.name)


def _load_local_plugins(registry: dict[str, type], plugins_dir: Path) -> None:
    if not plugins_dir.is_dir():
        log.warning("plugins_dir '%s' does not exist — skipping local plugins", plugins_dir)
        return
    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"datasure_plugin_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if isinstance(obj, type) and _is_valid_plugin(obj):
                    registry[obj.name] = obj
                    log.info("Plugin loaded from '%s': %s", path.name, obj.name)
        except Exception:
            log.exception("Failed to load local plugin from '%s'", path)


def _is_valid_plugin(cls: object) -> bool:
    return (
        isinstance(cls, type)
        and getattr(cls, "_is_datasure_plugin", False)
        and hasattr(cls, "name")
        and isinstance(getattr(cls, "name", None), str)
    )
