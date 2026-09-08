from __future__ import annotations


class ExternalServiceAuthorizationError(RuntimeError):
    """Sanitized authorization failure from an external service."""

    def __init__(
        self,
        service: str,
        *,
        status_code: int,
        operation: str,
    ) -> None:
        super().__init__(f"{service} authorization failed")
        self.service = service
        self.status_code = status_code
        self.operation = operation


class TransientExternalServiceError(RuntimeError):
    def __init__(
        self,
        service: str,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.retry_after_seconds = retry_after_seconds
