import grpc
import json
import datetime
import jsontransfer_pb2
import jsontransfer_pb2_grpc
import logging

_logger = logging.getLogger(__name__)

def send_json_payload(payload: str, source: str = "default"):
    try:
        # Connect to the gRPC server
        with grpc.insecure_channel("172.20.128.6:50051") as channel:
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
            _logger.warning("JSON message sent successfully.")
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

if __name__ == "__main__":
    send_json_payload()