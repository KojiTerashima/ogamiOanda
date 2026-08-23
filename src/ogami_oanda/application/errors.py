from __future__ import annotations


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
