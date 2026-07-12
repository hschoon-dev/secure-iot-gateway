"""cpc-partition/grpc_sender/grpc_sender.py

Reusable mTLS-secured gRPC sender with:
 - lazy channel + stub init (stub/channel are created on first use)
 - reconnect on transport-ish failures
 - optional single retry
 - thread-safe usage

This module also keeps a small per-destination sender cache and exposes
`send_json_payload(...)` for backward compatibility with existing code.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

import grpc

try:
    # Prefer package-relative imports if generated modules are placed alongside this file.
    from . import jsontransfer_pb2  # type: ignore
    from . import jsontransfer_pb2_grpc  # type: ignore
except Exception:  # pragma: no cover
    # Fallback to absolute imports used in the original codebase / docker build step.
    import jsontransfer_pb2  # type: ignore
    import jsontransfer_pb2_grpc  # type: ignore


_logger = logging.getLogger(__name__)


KEEPALIVE_OPTS: list[tuple[str, Any]] = [
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.http2.min_time_between_pings_ms", 10_000),
    ("grpc.http2.min_ping_interval_without_data_ms", 10_000),
]


def _load_ssl_credentials(certs: "GrpcClientCerts") -> grpc.ChannelCredentials:
    """Build mTLS channel credentials from a GrpcClientCerts config instance."""
    cert_base = _resolve_certs_base()
    if cert_base is not None:
        ca_cert = cert_base / "ca" / "ca.crt"
        client_key = cert_base / "client" / "client.key"
        client_cert = cert_base / "client" / "client.crt"
    else:
        ca_cert = Path(certs.ca_cert)
        client_key = Path(certs.client_key)
        client_cert = Path(certs.client_cert)

    try:
        root_certificates = ca_cert.read_bytes()
        private_key = client_key.read_bytes()
        certificate_chain = client_cert.read_bytes()

        return grpc.ssl_channel_credentials(
            root_certificates=root_certificates,
            private_key=private_key,
            certificate_chain=certificate_chain,
        )
    except Exception:
        _logger.exception("Failed to load TLS certificates")
        raise


def _resolve_certs_base() -> Path | None:
    secrets_root = Path(os.getenv("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    runtime_base = Path(
        os.getenv("CPC_GRPC_CERT_BASE", str(secrets_root / "cpc-partition" / "certs"))
    )
    if runtime_base.exists():
        return runtime_base

    # Explicit development compatibility only; production fails closed.
    project_root = Path(__file__).resolve().parents[1]
    rel_base = project_root / "certs"
    abs_base = Path("/certs")
    if os.getenv("ALLOW_LEGACY_SECRETS", "false").lower() in ("1", "true", "yes", "on"):
        legacy_base = rel_base if rel_base.exists() else abs_base
        _logger.warning(
            "Using legacy cpc gRPC cert path because ALLOW_LEGACY_SECRETS=true: %s",
            legacy_base,
        )
        # Returning None preserves the current config-driven development paths.
        return None
    raise FileNotFoundError(
        f"Runtime gRPC certificate directory not found: {runtime_base}. "
        "Legacy fallback is disabled."
    )


class GrpcJsonSender:
    """Reusable gRPC sender.

    Designed to be created once per destination and reused.
    """

    def __init__(
        self,
        target: str,
        ssl_credentials: grpc.ChannelCredentials,
        *,
        options: Optional[list[tuple[str, Any]]] = None,
        enable_retry: bool = True,
        timeout_s: float = 2.0,
    ) -> None:
        if not target:
            raise ValueError("target must not be empty")

        self._target = target
        self._creds = ssl_credentials
        self._options = options if options is not None else KEEPALIVE_OPTS
        self._enable_retry = enable_retry
        self._timeout_s = timeout_s

        self._lock = threading.RLock()
        self._channel: Optional[grpc.Channel] = None
        self._stub: Optional[jsontransfer_pb2_grpc.JsonSenderStub] = None

        # small reconnect backoff to avoid busy-looping on a down server
        self._last_failure = 0.0
        self._backoff_s = 1.0

    def _connect_locked(self) -> None:
        """Create channel + stub (call only while holding lock)."""
        self._channel = grpc.secure_channel(self._target, self._creds, options=self._options)
        self._stub = jsontransfer_pb2_grpc.JsonSenderStub(self._channel)
        _logger.info("gRPC channel initialized for %s", self._target)

    def _ensure_connected(self) -> jsontransfer_pb2_grpc.JsonSenderStub:
        with self._lock:
            if self._stub is not None:
                return self._stub

            now = time.monotonic()
            delta = now - self._last_failure
            if delta < self._backoff_s:
                time.sleep(self._backoff_s - delta)

            self._connect_locked()
            assert self._stub is not None
            return self._stub

    def _reset_connection(self) -> None:
        with self._lock:
            channel = self._channel
            self._channel = None
            self._stub = None
            self._last_failure = time.monotonic()

        try:
            if channel is not None:
                channel.close()
        except Exception:
            _logger.debug("Error while closing channel", exc_info=True)

    def close(self) -> None:
        self._reset_connection()

    @staticmethod
    def _should_reconnect(error: grpc.RpcError) -> bool:
        # Only reconnect on transport-ish failures.
        reconnect_codes = {
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.INTERNAL,
            grpc.StatusCode.UNKNOWN,
        }
        try:
            return error.code() in reconnect_codes
        except Exception:
            return True

    def send(self, json_payload: str, *, source: str = "default") -> Optional[object]:
        """Send JSON message.

        Returns the gRPC response (google.protobuf.Empty) on success.
        Returns None on handled errors.
        """

        # If payload is not a string, encode once.
        json_str = json.dumps(json_payload) if not isinstance(json_payload, str) else json_payload

        timestamp = datetime.datetime.now(datetime.timezone.utc)
        message = jsontransfer_pb2.JsonMessage(
            id=timestamp.isoformat(),
            source=source,
            json_payload=json_str,
        )

        def _do_send():
            stub = self._ensure_connected()
            return stub.SendJson(message, timeout=self._timeout_s)

        try:
            resp = _do_send()
            self._backoff_s = 1.0
            return resp
        except grpc.RpcError as e:
            # reconnect on transport errors
            if not self._should_reconnect(e):
                _logger.error("gRPC send failed (%s): %s", getattr(e.code(), "name", lambda: "?")(), e)
                return None

            _logger.warning("gRPC send failed (%s). Reconnecting...", e.code())
            self._reset_connection()

            if not self._enable_retry:
                return None

            # exponential backoff (cap 10s)
            self._backoff_s = min(self._backoff_s * 2, 10.0)
            try:
                return _do_send()
            except grpc.RpcError as e2:
                _logger.error("gRPC send failed after retry (%s): %s", e2.code(), e2)
                return None
        except Exception as e:
            _logger.error("Unexpected error during gRPC send: %s", e)
            self._reset_connection()
            return None


# ------------------------------
# Backward-compatible helpers
# ------------------------------

_SENDER_CACHE_LOCK = threading.RLock()
_SENDER_CACHE: dict[str, GrpcJsonSender] = {}
_SSL_CREDS: grpc.ChannelCredentials | None = None


def init_ssl_credentials(certs: "GrpcClientCerts") -> None:
    """
    Initialise the module-level SSL credentials from config.
    Call this once from main.py before any send_json_payload() calls:

        from grpc_sender import init_ssl_credentials
        init_ssl_credentials(CONFIG.grpc_certs)
    """
    global _SSL_CREDS
    _SSL_CREDS = _load_ssl_credentials(certs)


def get_sender(dest: str) -> GrpcJsonSender:
    """Get or create a cached sender for `dest` (host:port)."""
    if not dest:
        raise ValueError("dest must not be empty")
    if _SSL_CREDS is None:
        raise RuntimeError(
            "SSL credentials not initialised. Call init_ssl_credentials(config.grpc_certs) "
            "from main.py before using get_sender()."
        )
    with _SENDER_CACHE_LOCK:
        sender = _SENDER_CACHE.get(dest)
        if sender is None:
            sender = GrpcJsonSender(dest, _SSL_CREDS, options=KEEPALIVE_OPTS)
            _SENDER_CACHE[dest] = sender
        return sender


def close_all_senders() -> None:
    """Close and clear all cached senders."""
    with _SENDER_CACHE_LOCK:
        items = list(_SENDER_CACHE.items())
        _SENDER_CACHE.clear()
    for _, sender in items:
        try:
            sender.close()
        except Exception:
            _logger.debug("Error closing sender", exc_info=True)


def send_json_payload(payload: str, source: str = "default", dest: Optional[str] = None):
    """Backward-compatible API.

    Uses cached GrpcJsonSender per destination (lazy init + reconnect).
    """
    if not dest:
        raise ValueError("dest darf für einen gRPC-Call nicht None sein")
    return get_sender(dest).send(payload, source=source)
