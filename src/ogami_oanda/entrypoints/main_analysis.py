"""Bind the main-source backend when composing the built-in original strategy."""

from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.source import DEFAULT_SOURCE_DIRECTORY
from ogami_oanda.domain.analysis.main_contracts import validate_main_analysis_name


def validate_analysis_selection(strategy, analysis_name):
    """An explicit selection must be supported, never silently ignored."""
    if analysis_name is not None:
        validate_main_analysis_name(analysis_name)
        if analysis_name not in getattr(strategy, "supported_main_analyses", ()):
            raise ValueError("--analysis requires an original strategy supporting main analysis selection")


def analysis_strategy_id(strategy_id, backend):
    """Keep historical line identities; distinguish other analysis checkpoints."""
    name = getattr(backend, "analysis_name", None)
    if name is None or name == "line":
        return strategy_id
    suffix = f":analysis={name}"
    return strategy_id if strategy_id.endswith(suffix) else strategy_id + suffix


def bind_main_analysis(strategy, *, mode, main_analysis_dir=DEFAULT_SOURCE_DIRECTORY, analysis_name=None):
    """Preserve explicit dependencies while setting the composition's clock mode."""
    validate_analysis_selection(strategy, analysis_name)
    bind = getattr(strategy, "bind_main_analysis", None)
    if not callable(bind):
        if analysis_name is not None:
            raise ValueError("selected strategy cannot bind main analysis")
        return None
    backend = getattr(getattr(strategy, "analysis", None), "analysis_backend", None)
    if backend is None:
        if not getattr(strategy, "_use_main_analysis_default", True):
            if analysis_name is not None:
                raise ValueError("--analysis conflicts with the injected analysis or candidate builder")
            return None
        backend = MainSourceAnalysis(source_directory=main_analysis_dir, analysis_name=analysis_name or "line")
    elif analysis_name is not None and getattr(backend, "analysis_name", None) != analysis_name:
        raise ValueError("--analysis conflicts with the injected backend or that backend cannot select an analysis")
    bind(backend, mode=mode)
    return backend
