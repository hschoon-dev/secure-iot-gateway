"""Minimal generic gRPC endpoint used only by the isolated rotation test."""

from __future__ import annotations

import signal
import sys
import threading
from concurrent import futures
from pathlib import Path

import grpc


def read(path: str) -> bytes:
    return Path(path).read_bytes()


def serve(key: str, certificate: str, ca: str) -> None:
    credentials = grpc.ssl_server_credentials(
        [(read(key), read(certificate))],
        root_certificates=read(ca),
        require_client_auth=True,
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    handler = grpc.method_handlers_generic_handler(
        "rotation.Probe",
        {
            "Ping": grpc.unary_unary_rpc_method_handler(
                lambda request, context: b"pong",
                request_deserializer=lambda value: value,
                response_serializer=lambda value: value,
            )
        },
    )
    server.add_generic_rpc_handlers((handler,))
    if server.add_secure_port("[::]:50054", credentials) == 0:
        raise RuntimeError("could not bind rotation probe")
    server.start()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    signal.signal(signal.SIGINT, lambda *_args: stopped.set())
    stopped.wait()
    server.stop(grace=1).wait()


def ping(target: str, key: str, certificate: str, ca: str) -> None:
    credentials = grpc.ssl_channel_credentials(
        root_certificates=read(ca),
        private_key=read(key),
        certificate_chain=read(certificate),
    )
    with grpc.secure_channel(
        target,
        credentials,
        options=(("grpc.ssl_target_name_override", "cpc-partition"),),
    ) as channel:
        grpc.channel_ready_future(channel).result(timeout=5)
        response = channel.unary_unary("/rotation.Probe/Ping")(b"ping", timeout=3)
    if response != b"pong":
        raise AssertionError(f"unexpected probe response: {response!r}")


if __name__ == "__main__":
    mode, *arguments = sys.argv[1:]
    if mode == "server":
        serve(*arguments)
    elif mode == "client":
        ping(*arguments)
    else:
        raise SystemExit("usage: grpc_probe.py server|client ...")
