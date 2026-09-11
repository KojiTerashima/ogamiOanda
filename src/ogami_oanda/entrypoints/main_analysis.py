"""Bind the main-source backend when composing the built-in original strategy."""

from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.source import DEFAULT_SOURCE_DIRECTORY


def bind_main_analysis(strategy, *, mode, main_analysis_dir=DEFAULT_SOURCE_DIRECTORY):
    """Preserve explicit dependencies while setting the composition's clock mode."""
    bind = getattr(strategy, "bind_main_analysis", None)
    if not callable(bind):
        return None
    backend = getattr(getattr(strategy, "analysis", None), "analysis_backend", None)
    if backend is None:
        if not getattr(strategy, "_use_main_analysis_default", True):
            return None
        backend = MainSourceAnalysis(source_directory=main_analysis_dir)
    bind(backend, mode=mode)
    return backend
