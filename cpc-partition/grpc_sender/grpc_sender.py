import grpc
import json
import jsontransfer_pb2
import jsontransfer_pb2_grpc

#from grpc_sender import jsontransfer_pb2, jsontransfer_pb2_grpc

def send_json_payload():
    with grpc.insecure_channel("172.20.128.6:50051") as channel:
        stub = jsontransfer_pb2_grpc.JsonSenderStub(channel)
        
        # Example JSON data
        payload = {
            "temperature": 22.5,
            "humidity": 48,
            "status": "ok"
        }

        message = jsontransfer_pb2.JsonMessage(
            id="123",
            source="Ecotec",
            json_payload=json.dumps(payload)
        )

        response = stub.SendJson(message)
        print("Sent JSON message successfully.")
        return response

if __name__ == "__main__":
    send_json_payload()
