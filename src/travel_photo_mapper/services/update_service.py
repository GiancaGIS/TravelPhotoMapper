from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from travel_photo_mapper.app_info import APP_NAME, APP_VERSION, GITHUB_REPOSITORY


LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
API_VERSION = "2026-03-10"
REQUEST_TIMEOUT_MS = 12_000
_VERSION = re.compile(
    r"[vV]?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def version_key(value: str) -> tuple:
    """Compare SemVer tags numerically, ignoring v prefixes and build metadata."""
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f"Unsupported version: {value}")
    prerelease = match[4]
    identifiers = []
    if prerelease:
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    raise ValueError(f"Unsupported version: {value}")
                identifiers.append((0, int(identifier)))
            else:
                identifiers.append((1, identifier))
    return (tuple(int(match[index]) for index in (1, 2, 3)),
            prerelease is None, tuple(identifiers))


@dataclass(frozen=True, slots=True)
class UpdateResult:
    status: str
    tag: str = ""
    release_url: str = ""
    notes: str = ""
    http_status: int = 0
    retry_after: int = 0


def release_result(payload, current_version: str = APP_VERSION) -> UpdateResult:
    if not isinstance(payload, dict):
        return UpdateResult("invalid_response")
    if payload.get("draft") is True or payload.get("prerelease") is True:
        return UpdateResult("no_release")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return UpdateResult("invalid_response")
    try:
        latest = version_key(tag)
    except ValueError:
        return UpdateResult("unsupported_tag", tag=tag)
    if not latest[1]:
        return UpdateResult("no_release")
    status = "available" if latest > version_key(current_version) else "up_to_date"
    # Build the link ourselves: response fields must not choose an external destination.
    url = f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/{quote(tag, safe='')}"
    notes = payload.get("body")
    return UpdateResult(status, tag, url, notes if isinstance(notes, str) else "")


def retry_delay(headers: dict[str, str], now: float | None = None) -> int:
    now = time.time() if now is None else now
    retry_after = headers.get("retry-after", "")
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(retry_after).timestamp() - now
            except (ValueError, TypeError, OverflowError):
                seconds = 0
        if math.isfinite(seconds) and seconds > 0:
            return max(1, math.ceil(seconds))
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            seconds = float(headers.get("x-ratelimit-reset", "")) - now
            if math.isfinite(seconds) and seconds > 0:
                return max(1, math.ceil(seconds))
        except ValueError:
            pass
    return 60


class UpdateChecker(QObject):
    """One asynchronous GitHub request at a time, with caching and rate-limit handling."""

    finished = pyqtSignal(object)

    def __init__(self, parent=None, *, manager=None, current_version=APP_VERSION):
        super().__init__(parent)
        self._manager = manager if manager is not None else QNetworkAccessManager(self)
        self._current_version = current_version
        self._reply = None
        self._retry_at = 0.0
        self._etag = b""
        self._cached_result: UpdateResult | None = None

    @property
    def busy(self) -> bool:
        return self._reply is not None

    def check(self) -> bool:
        if self.busy:
            return False
        remaining = self._retry_at - time.monotonic()
        if remaining > 0:
            self.finished.emit(UpdateResult("rate_limited", retry_after=math.ceil(remaining)))
            return False
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"{APP_NAME.replace(' ', '')}/{APP_VERSION}".encode("ascii"))
        request.setRawHeader(b"X-GitHub-Api-Version", API_VERSION.encode("ascii"))
        if self._etag and self._cached_result is not None:
            request.setRawHeader(b"If-None-Match", self._etag)
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._on_finished)
        return True

    def cancel(self):
        reply = self._reply
        if reply is not None:
            self._reply = None
            reply.finished.disconnect(self._on_finished)
            reply.abort()
            reply.deleteLater()

    def _on_finished(self):
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            headers = {bytes(name).decode("ascii", errors="replace").lower():
                       bytes(value).decode("ascii", errors="replace")
                       for name, value in reply.rawHeaderPairs()}
            if status == 304 and self._cached_result is not None:
                result = self._cached_result
            elif status == 404:
                result = UpdateResult("no_release")
            elif status in (403, 429):
                delay = retry_delay(headers)
                self._retry_at = time.monotonic() + delay
                result = UpdateResult("rate_limited", retry_after=delay)
            elif status >= 400:
                result = UpdateResult("http_error", http_status=status)
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                timed_out = reply.error() in (
                    QNetworkReply.NetworkError.TimeoutError,
                    QNetworkReply.NetworkError.OperationCanceledError,
                )
                result = UpdateResult("timeout" if timed_out else "network_error")
            elif status == 200:
                self._etag = b""
                self._cached_result = None
                try:
                    payload = json.loads(bytes(reply.readAll()))
                except (ValueError, UnicodeError):
                    result = UpdateResult("invalid_response")
                else:
                    result = release_result(payload, self._current_version)
                    if result.status in ("available", "up_to_date"):
                        self._etag = bytes(reply.rawHeader(b"ETag"))
                        self._cached_result = result
            else:
                result = UpdateResult("invalid_response")
        finally:
            reply.deleteLater()
        self.finished.emit(result)
