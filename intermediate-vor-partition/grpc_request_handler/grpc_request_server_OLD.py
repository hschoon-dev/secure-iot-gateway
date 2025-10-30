import grpc
from concurrent import futures
from datetime import datetime, timezone
from pathlib import Path
import logging

import request_pb2, request_pb2_grpc

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
    def Submit(self, request, context):
        server_recv_utc = datetime.now(timezone.utc)
        try:
            client_ts_utc = _parse_iso8601(request.timestamp)
            _logger.info(f"Client UTC timestamp: {client_ts_utc}")
        except Exception as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid ISO-8601 timestamp: {e}")
            _logger.error(f"Error: {e}")
            return request_pb2.SubmitResponse()

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

        ack = f"ACK for issuer_id={request.request_id}, priority={request.priority}"
        server_ts_str = server_recv_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        return request_pb2.SubmitResponse(
            ack=ack,
            server_timestamp=server_ts_str
        )

def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()

def build_grpc_server(
    port: int = 50051,
    cert_base: Path | None = None,
    max_workers: int = 10,
):
    """
    Build (but do not block on) a gRPC server with mTLS.
    Returns (server, bind_addr) so caller can start/stop it.
    """
    #if cert_base is None:
        # Try repo-relative first, then absolute mount.
        #here = Path(__file__).resolve().parent
        #rel = here.parent / "certificates" / "grpc"
        #cert_base = rel if rel.exists() else Path("/certificates/grpc")

    ca = _read_bytes(cert_base / "ca" / "ca.crt")
    key = _read_bytes(cert_base / "server" / "server.key")
    crt = _read_bytes(cert_base / "server" / "server.crt")

    creds = grpc.ssl_server_credentials(
        [(key, crt)],
        root_certificates=ca,          # trust CA that signs client certs
        require_client_auth=True
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    request_pb2_grpc.add_RequestServiceServicer_to_server(RequestService(), server)

    bind_addr = f"[::]:{port}"  # or "0.0.0.0:port"
    server.add_secure_port(bind_addr, creds)
    return server, bind_addr
