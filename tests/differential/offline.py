from __future__ import annotations

import contextlib
import socket
from dataclasses import dataclass, field


class OfflineNetworkError(AssertionError):
    pass


@dataclass
class OfflineNetworkGuard:
    calls: list[str] = field(default_factory=list)
    _request_original: object | None = None
    _socket_original: object | None = None
    _connection_original: object | None = None

    def install(self) -> None:
        import requests.sessions

        self._request_original = requests.sessions.Session.request
        self._socket_original = socket.socket
        self._connection_original = socket.create_connection

        def _blocked_request(session, method, url, *args, **kwargs):
            del session, args, kwargs
            call = f"requests:{method}:{url}"
            self.calls.append(call)
            raise OfflineNetworkError(
                f"Network access is prohibited in differential runner: {call}"
            )

        def _blocked_socket(*args, **kwargs):
            del args, kwargs
            self.calls.append("socket")
            raise OfflineNetworkError(
                "Network access is prohibited in differential runner: socket"
            )

        def _blocked_connection(*args, **kwargs):
            del args, kwargs
            self.calls.append("socket.create_connection")
            raise OfflineNetworkError(
                "Network access is prohibited in differential runner: socket.create_connection"
            )

        requests.sessions.Session.request = _blocked_request
        socket.socket = _blocked_socket
        socket.create_connection = _blocked_connection

    def uninstall(self) -> None:
        import requests.sessions

        if self._request_original is not None:
            requests.sessions.Session.request = self._request_original
        if self._socket_original is not None:
            socket.socket = self._socket_original
        if self._connection_original is not None:
            socket.create_connection = self._connection_original

    def assert_no_calls(self) -> None:
        if self.calls:
            raise OfflineNetworkError(
                f"Network call attempted in differential runner: {self.calls[0]}"
            )


@contextlib.contextmanager
def offline_network_guard():
    guard = OfflineNetworkGuard()
    guard.install()
    try:
        yield guard
        guard.assert_no_calls()
    finally:
        guard.uninstall()
