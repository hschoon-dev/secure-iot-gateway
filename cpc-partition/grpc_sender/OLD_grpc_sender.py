import grpc
import json
import datetime
import jsontransfer_pb2
import jsontransfer_pb2_grpc
from pathlib import Path
import logging

_logger = logging.getLogger(__name__)

"""def send_json_payload(payload: str, source: str = "default", dest: str = None):
    try:
        # Connect to the gRPC server of the psmo-Partition
        with grpc.insecure_channel(dest) as channel:
            stub = jsontransfer_pb2_grpc.JsonSenderStub(channel)

            timestamp = datetime.datetime.now(datetime.timezone.utc)

            # Build the protobuf message
            message = jsontransfer_pb2.JsonMessage(
                id=timestamp.isoformat(),
                source=source,
                json_payload=json.dumps(payload)
            )

            # Try sending
            response = stub.SendJson(message)
            _logger.info("JSON message sent successfully.")
            return response

    except grpc.RpcError as e:
        _logger.error(f"gRPC error: {e.code().name} - {e.details()}")
        return None

    except json.JSONDecodeError as e:
        _logger.error(f"JSON encoding error: {e}")
        return None

    except Exception as e:
        _logger.error(f"Unexpected error: {e}")
        return None"""

project_root = Path(__file__).resolve().parents[1]
rel_base = project_root / "certs"
abs_base = Path("/certs")

cert_base = rel_base if rel_base.exists() else abs_base

CLIENT_CERT = cert_base / "client" / "client.crt"
CLIENT_KEY  = cert_base / "client" / "client.key"
CA_CERT     = cert_base / "ca"     / "ca.crt"

# Globale Credentials einmal bauen und dann wiederverwenden
def _load_ssl_credentials() -> grpc.ChannelCredentials:
    try:
        root_certificates = CA_CERT.read_bytes()
        private_key = CLIENT_KEY.read_bytes()
        certificate_chain = CLIENT_CERT.read_bytes()

        return grpc.ssl_channel_credentials(
            root_certificates=root_certificates,
            private_key=private_key,
            certificate_chain=certificate_chain,
        )
    except Exception as e:
        _logger.error(f"Fehler beim Laden der TLS-Zertifikate: {e}")
        raise

_SSL_CREDS = _load_ssl_credentials()


def _create_secure_channel(dest: str) -> grpc.Channel:
    """
    Baut einen mTLS-gesicherten Channel zu `dest`.

    `dest` ist wie gehabt der gRPC-Target-String, z.B. "host:port".
    Wenn deine Server-Zertifikate einen anderen CN/SAN-Namen haben
    als `host`, kannst du hier noch Optionen setzen (s.u.).
    """
    if not dest:
        raise ValueError("dest must not be None or empty")

    # Falls der Common Name / SAN im Zertifikat nicht mit dest übereinstimmt,
    # kannst du das hier überschreiben (Beispiel auskommentiert):
    #
    # options = (("grpc.ssl_target_name_override", "dns.name.im.zertifikat"),)
    # return grpc.secure_channel(dest, _SSL_CREDS, options=options)

    return grpc.secure_channel(dest, _SSL_CREDS)


def send_json_payload(payload: str, source: str = "default", dest: str = None):
    """
    Sendet JSON per mTLS-gesichertem gRPC an `dest`.

    Hinweis: Falls `payload` eigentlich schon ein JSON-String ist,
    solltest du json.dumps(payload) unten weglassen, sonst wird doppelt encodiert.
    """
    try:
        if dest is None:
            raise ValueError("dest darf für einen gRPC-Call nicht None sein")

        # mTLS-Channel statt insecure_channel
        with _create_secure_channel(dest) as channel:
            stub = jsontransfer_pb2_grpc.JsonSenderStub(channel)

            timestamp = datetime.datetime.now(datetime.timezone.utc)

            # Wenn payload ein dict/objekt ist: json.dumps(payload)
            # Wenn payload bereits JSON-String ist: einfach payload verwenden
            json_str = json.dumps(payload) if not isinstance(payload, str) else payload

            message = jsontransfer_pb2.JsonMessage(
                id=timestamp.isoformat(),
                source=source,
                json_payload=json_str,
            )

            response = stub.SendJson(message)
            _logger.info("JSON message sent successfully.")
            return response

    except grpc.RpcError as e:
        _logger.error(f"gRPC error: {e.code().name} - {e.details()}")
        return None

    except json.JSONDecodeError as e:
        _logger.error(f"JSON encoding error: {e}")
        return None

    except Exception as e:
        _logger.error(f"Unexpected error: {e}")
        return None