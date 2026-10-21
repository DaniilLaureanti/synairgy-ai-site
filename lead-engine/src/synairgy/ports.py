"""Replaceable I/O contracts; orchestration doesn't instantiate providers."""

from typing import Protocol


class Inspector(Protocol):
    def inspect(self, place: dict) -> dict: ...


class Analyzer(Protocol):
    def analyze(self, place: dict, site: dict) -> dict: ...


class Sender(Protocol):
    def send(self, *, recipient: str, subject: str, body: str, message_id: str, unsubscribe_url: str) -> str: ...


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, *, blocked: bool = False, permanent: bool = False):
        super().__init__(code)
        self.code, self.blocked, self.permanent = code, blocked, permanent
