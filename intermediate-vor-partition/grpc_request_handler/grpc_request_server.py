# server.py
import grpc
from concurrent import futures
from datetime import datetime, timezone
from pathlib import Path
import logging

import request_pb2, request_pb2_grpc
from request_message_handler import RequestMessageHandler

REALTIME_BOUND_MS = 1500
_logger = logging.getLogger(__name__)

def _parse_iso8601(ts: str):
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

class RequestService(request_pb2_grpc.RequestServiceServicer):
    def __init__(self, handler: RequestMessageHandler):
        self._handler = handler

    def Submit(self, request, context):
        # Record server receive time ASAP
        server_recv_utc = datetime.now(timezone.utc)

        # Parse client timestamp + compute latency (for logs / SLA check)
        try:
            client_ts_utc = _parse_iso8601(request.timestamp)
        except Exception as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid ISO-8601 timestamp: {e}")
            _logger.error("Timestamp parse error: %s", e)
            return request_pb2.SubmitResponse()

        latency_ms = int((server_recv_utc - client_ts_utc).total_seconds() * 1000)
        within_bounds = (latency_ms >= 0) and (latency_ms <= REALTIME_BOUND_MS)

        _logger.warning(f"Request received:")
        _logger.warning(f"  {str(request.issuer_id)}")
        _logger.warning(f"  {str(request.issuer_characteristics)}")
        _logger.warning(f"  {str(request.timestamp)}")
        _logger.warning(f"  {str(request.description)}")
        _logger.warning(f"  {str(request.impact)}")
        _logger.warning(f"  {str(request.parameters)}")
        _logger.warning(f"  {str(request.modification)}")
        _logger.warning(f"  {str(request.priority)}")
        _logger.warning(f"  {str(request.request_id)}")

        # === Process BEFORE replying ===
        try:
            verified_rq = self._handler.handle_grpc_submit(request)
        except Exception as e:
            # Map domain-specific failures to appropriate gRPC codes
            _logger.error("Processing failure: %s", e, exc_info=True)
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f"Request verification/mapping failed: {e}")
            return request_pb2.SubmitResponse()

        # Build response
        ack = f"ACK for request_id={getattr(request, 'request_id', '')}, priority={request.priority}"
        if not within_bounds:
            # Keep the wire response minimal; log the SLA miss
            _logger.warning("Latency %d ms exceeds realtime bound (%d ms).", latency_ms, REALTIME_BOUND_MS)
        else:
            _logger.info("Latency %d ms within realtime bound (%d ms).", latency_ms, REALTIME_BOUND_MS)

        server_ts_str = server_recv_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return request_pb2.SubmitResponse(
            ack=ack,
            server_timestamp=server_ts_str
        )

def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()

def build_grpc_server(
    handler: RequestMessageHandler,
    port: int = 50051,
    cert_base: Path | None = None,
    max_workers: int = 10,
):
    """
    Build (but don't block on) a gRPC server with mTLS.
    Caller is responsible for start()/stop().
    """
    if cert_base is None:
        here = Path(__file__).resolve().parent
        rel = here.parent / "certificates" / "grpc"
        cert_base = rel if rel.exists() else Path("/certificates/grpc")

    ca  = _read_bytes(cert_base / "ca"     / "ca.crt")
    key = _read_bytes(cert_base / "server" / "server.key")
    crt = _read_bytes(cert_base / "server" / "server.crt")

    creds = grpc.ssl_server_credentials(
        [(key, crt)],
        root_certificates=ca,
        require_client_auth=True
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    request_pb2_grpc.add_RequestServiceServicer_to_server(RequestService(handler), server)

    bind_addr = f"[::]:{port}"
    server.add_secure_port(bind_addr, creds)
    return server, bind_addr
