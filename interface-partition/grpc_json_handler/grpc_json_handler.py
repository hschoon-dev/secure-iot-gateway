"""
------------------------------------------------------------
 Modul:    psmo-partition/grpc_json_handler.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This plant-specific M+O handler module manages the
    inter-process communication via Remote Procedure Calls
    and Queues. It includes a thread to receive data from
    the gRPC-Client (cpc-partition) as a gRPC-Server.
    The content of the messages are defined by the .proto-
    file and contain:
        - id: str = Timestamp
        - source: str = {"default", "OPCUA", "MODBUSTCP"}
        - data: str = JSON-Payload
    For further processing the content of the queues can
    be extracted by another process.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - heiko.schoon@hs-emden-leer.de

 Hinweis:
    Ongoing development. This is a placeholder module
    for future plant-specific M+O implementations. It 
    currently only provides an API to read shared
    memory segments for OPC UA and Modbus TCP data.
------------------------------------------------------------
"""

from threading import Thread, Event
import json
import logging
from queue import Queue
import hashlib

import grpc
from concurrent import futures
from google.protobuf import empty_pb2
import jsontransfer_pb2_grpc


_logger = logging.getLogger(__name__)


class JsonSenderServicer(jsontransfer_pb2_grpc.JsonSenderServicer):
    def __init__(self, opcua_message_queue: Queue = None, modbustcp_message_queue: Queue = None):
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue

    def SendJson(self, request, context):
        _logger.debug(f"Received JSON message:")

        try:
            data = json.loads(request.json_payload)
            if request.source == "OPCUA":
                _logger.warning(f"Received data with length {len(data)} from OPC UA source on timestamp {request.id}.")
                _logger.debug(f"Parsed data: {data}")

                if self._opcua_queue is not None:
                    self._opcua_queue.put({
                        "timestamp": request.id,
                        "source": request.source,
                        "data": data
                    })
                    _logger.warning(f"Added payload to queue.")

            elif request.source == "MODBUSTCP":
                _logger.warning(f"Received data with length {len(data)} from ModbusTCP source on timestamp {request.id}.")
                _logger.debug(f"Parsed data: {data}")

                if self._modbustcp_queue is not None:
                    self._modbustcp_queue.put({
                        "timestamp": request.id,
                        "source": request.source,
                        "data": data
                    })
                    _logger.warning(f"Added payload to queue.")

            else:
                _logger.error(f"Received call from unknown source.")
                _logger.debug(f"Parsed data: {data}")



        # TODO: response = hashlib.sha256(opcua_values_json.encode()).hexdigest()
            
        except Exception as e:
            _logger.error(f"Failed to parse JSON: {e}")
        return empty_pb2.Empty()

class JSON_gRPC_Thread(Thread):
    def __init__(self, opcua_message_queue: Queue = None, modbustcp_message_queue: Queue = None):
        super().__init__(name="gRPC-Server", daemon=True)
        Thread.__init__(self)
        self._stop_event = Event()
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue

    def run(self):
        try:
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=2)) # TODO: look if we can reduce the number of threads even further to 1
            jsontransfer_pb2_grpc.add_JsonSenderServicer_to_server(JsonSenderServicer(opcua_message_queue=self._opcua_queue, modbustcp_message_queue=self._modbustcp_queue), server)
            server.add_insecure_port("[::]:50051")
            _logger.info(f"Server started on port 50051")
        except Exception as e:
            _logger.error(f"Error starting gRPC-Server: {e}")
        if server is not None:
            server.start()
            server.wait_for_termination()
        

    def stop(self):
        self._stop_event.set()