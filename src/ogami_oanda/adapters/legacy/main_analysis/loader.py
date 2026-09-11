"""Execute original modules using evaluation-local imports and output sinks."""

from __future__ import annotations

import builtins
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import lru_cache
import importlib
import io
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4

from ogami_oanda.domain.analysis.main_contracts import UnsupportedAnalysisDependency

from .source import COMPAT_MODULES, EXTERNAL_MODULES, read_sources

_HOST_IMPORT = builtins.__import__


@lru_cache(maxsize=128)
def _compiled(filename: str, content: bytes):
    return compile(content, filename, "exec")


def _forbidden(*args, **kwargs):
    raise UnsupportedAnalysisDependency("upstream analysis attempted external I/O")


class _UnavailableBroker:
    def __init__(self, *args, **kwargs):
        _forbidden()


class SourceRuntime:
    """One namespace per evaluation. Never aliases the host's legacy imports."""

    def __init__(self, *, sources=None, evaluation_time=None, artifact_directory: Path | None = None):
        sources = sources if sources is not None else read_sources()
        self.source_directory, self.contents = sources.directory, sources.contents
        self.prefix = f"_ogami_main_{uuid4().hex}"
        self.modules: dict[str, ModuleType] = {}
        self.shims: dict[str, ModuleType] = {}
        self.messages: list[str] = []
        self.output = io.StringIO()
        self._sink = ContextVar(self.prefix, default=self.output)
        self.closed = False
        self.evaluation_time = evaluation_time
        self.artifact_directory = artifact_directory
        package = ModuleType(self.prefix)
        package.__path__ = []
        sys.modules[self.prefix] = package

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for name in self.modules:
            sys.modules.pop(f"{self.prefix}.{name}", None)
        sys.modules.pop(self.prefix, None)
        self.modules.clear()
        self.shims.clear()
        self.closed = True

    def _print(self, *args, **kwargs):
        destination = kwargs.get("file")
        if destination is None or destination is sys.stdout or destination is sys.stderr:
            kwargs["file"] = self._sink.get()
        builtins.print(*args, **kwargs)

    @contextmanager
    def _redirect_stdout(self, destination):
        token = self._sink.set(destination)
        try:
            yield destination
        finally:
            self._sink.reset(token)

    def _notice(self, *messages, **kwargs):
        self.messages.append(" ".join(str(message) for message in messages))

    def _missing(self, name):
        raise UnsupportedAnalysisDependency(f"unsupported upstream dependency: {name}")

    def _shim(self, name):
        if name in self.shims:
            return self.shims[name]
        module = ModuleType(name)
        self.shims[name] = module
        if name == "tokens":
            if self.artifact_directory is not None:
                module.folder_path = str(self.artifact_directory)
            module.__getattr__ = lambda attr: self._missing(f"tokens.{attr}")
        elif name == "send_notice":
            module.line_send = self._notice
        elif name == "contextlib":
            host = importlib.import_module("contextlib")
            module.__dict__.update(vars(host))
            module.redirect_stdout = self._redirect_stdout
            module.redirect_stderr = self._redirect_stdout
        elif name == "sys":
            module.__dict__.update(vars(sys))
            module.stdout = self.output
            module.stderr = self.output
            module.exit = _forbidden
            module.path = tuple(sys.path)
        elif name == "datetime":
            host = importlib.import_module("datetime")
            module.__dict__.update(vars(host))
            if self.evaluation_time is None:
                return module
            instant = self.evaluation_time

            class EvaluationDateTime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

                @classmethod
                def utcnow(cls):
                    return instant.astimezone(host.timezone.utc).replace(tzinfo=None)

            module.datetime = EvaluationDateTime
        elif name == "requests":
            module.get = module.post = module.request = module.Session = _forbidden
            module.exceptions = importlib.import_module("requests.exceptions")
        elif name.startswith("oandapyV20"):
            module.__path__ = []
            module.API = _UnavailableBroker
            module.__getattr__ = lambda attr: _UnavailableBroker
        else:
            return _HOST_IMPORT(name, fromlist=["*"])
        return module

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            raise UnsupportedAnalysisDependency(f"unsupported relative main import: {name}")
        if name in self.contents:
            return self.load(name)
        if name == "_strptime":
            return _HOST_IMPORT(name, globals, locals, fromlist, level)
        root = name.split(".")[0]
        if root not in sys.stdlib_module_names | EXTERNAL_MODULES | COMPAT_MODULES:
            raise UnsupportedAnalysisDependency(f"unsupported main import: {name} in {self.source_directory}")
        if name in COMPAT_MODULES | {"contextlib", "sys", "requests", "datetime"} or name.startswith("oandapyV20"):
            module = self._shim(name)
            if "." in name and not fromlist:
                parts = name.split(".")
                for index in range(1, len(parts)):
                    parent = self._shim(".".join(parts[:index]))
                    setattr(parent, parts[index], self._shim(".".join(parts[:index + 1])))
                return self._shim(parts[0])
            return module
        return _HOST_IMPORT(name, globals, locals, fromlist, level)

    def load(self, name: str) -> ModuleType:
        if self.closed:
            raise RuntimeError("analysis session is closed")
        if name in self.modules:
            return self.modules[name]
        if name not in self.contents:
            raise UnsupportedAnalysisDependency(f"unsupported main analysis module: {name}")
        qualified = f"{self.prefix}.{name}"
        module = ModuleType(qualified)
        module.__package__ = self.prefix
        module.__file__ = str(self.source_directory / f"{name}.py")
        module.__dict__["__builtins__"] = dict(vars(builtins), __import__=self._import, print=self._print)
        self.modules[name] = module
        sys.modules[qualified] = module
        try:
            exec(_compiled(module.__file__, self.contents[name]), module.__dict__)
        except (ImportError, SyntaxError) as error:
            self.close()
            raise UnsupportedAnalysisDependency(f"cannot load main analysis source: {module.__file__}: {error}") from error
        except BaseException:
            self.close()
            raise
        return module

    @contextmanager
    def binding(self, module, name, value):
        """Bind an environment boundary in this private namespace only."""
        previous = getattr(module, name)
        setattr(module, name, value)
        try:
            yield
        finally:
            setattr(module, name, previous)
