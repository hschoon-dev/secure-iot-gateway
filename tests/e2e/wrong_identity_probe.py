"""Assert denial of a foreign or obsolete mTLS client identity."""

from __future__ import annotations

import argparse
from pathlib import Path

import grpc


def read(path: str) -> bytes:
    return Path(path).read_bytes()


def invoke(rpc: str, channel: grpc.Channel) -> None:
    if rpc == "request":
        import request_pb2
        import request_pb2_grpc

        request_pb2_grpc.RequestServiceStub(channel).Submit(
            request_pb2.SubmitRequest(), timeout=3.0
        )
    elif rpc == "processing":
        import pipeline_pb2
        import pipeline_pb2_grpc

        pipeline_pb2_grpc.ProcessingServiceStub(channel).Process(
            pipeline_pb2.MappedRequest(), timeout=3.0
        )
    elif rpc == "cpc":
        import pipeline_pb2
        import pipeline_pb2_grpc

        pipeline_pb2_grpc.CpcServiceStub(channel).ReadValues(
            pipeline_pb2.ReadValuesRequest(), timeout=3.0
        )
    elif rpc == "json":
        import jsontransfer_pb2
        import jsontransfer_pb2_grpc

        jsontransfer_pb2_grpc.JsonSenderStub(channel).SendJson(
            jsontransfer_pb2.JsonMessage(
                id="wrong-identity-probe", source="OPCUA", json_payload="{}"
            ),
            timeout=3.0,
        )
    else:
        raise ValueError(f"unsupported RPC kind: {rpc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rpc", choices=("request", "processing", "cpc", "json"))
    parser.add_argument("target")
    parser.add_argument("server_name")
    parser.add_argument("key")
    parser.add_argument("certificate")
    parser.add_argument("ca")
    parser.add_argument("--connect-timeout", type=float, default=20.0)
    parser.add_argument(
        "--expect",
        choices=("accepted-identity", "permission-denied", "tls-rejected"),
        default="permission-denied",
    )
    args = parser.parse_args()

    credentials = grpc.ssl_channel_credentials(
        root_certificates=read(args.ca),
        private_key=read(args.key),
        certificate_chain=read(args.certificate),
    )
    with grpc.secure_channel(
        args.target,
        credentials,
        options=(("grpc.ssl_target_name_override", args.server_name),),
    ) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=args.connect_timeout)
        except grpc.FutureTimeoutError as exc:
            if args.expect == "tls-rejected":
                print(
                    "PASS obsolete-identity: "
                    f"{args.rpc} at {args.target} rejected old trust at TLS handshake"
                )
                return
            raise AssertionError(
                f"expected application-level denial, but TLS channel was not established: "
                f"{args.rpc} at {args.target}"
            ) from exc

        if args.expect == "tls-rejected":
            raise AssertionError(
                f"{args.rpc} at {args.target} established TLS with an obsolete certificate"
            )

        try:
            invoke(args.rpc, channel)
        except grpc.RpcError as exc:
            if args.expect == "accepted-identity":
                if exc.code() in {
                    grpc.StatusCode.PERMISSION_DENIED,
                    grpc.StatusCode.UNAUTHENTICATED,
                    grpc.StatusCode.UNAVAILABLE,
                }:
                    raise AssertionError(
                        f"intended identity was not accepted: {exc.code().name}: "
                        f"{exc.details()}"
                    ) from exc
                print(
                    "PASS intended-identity: transport accepted; "
                    f"application returned {exc.code().name}"
                )
                return
            if exc.code() == grpc.StatusCode.PERMISSION_DENIED:
                print(
                    "PASS wrong-service-identity: "
                    f"{args.rpc} at {args.target} rejected valid foreign certificate"
                )
                return
            raise AssertionError(
                f"expected PERMISSION_DENIED, got {exc.code().name}: {exc.details()}"
            ) from exc

        if args.expect == "accepted-identity":
            print(
                "PASS intended-identity: "
                f"{args.rpc} at {args.target} accepted the intended certificate"
            )
            return

    raise AssertionError(f"{args.rpc} at {args.target} accepted a foreign certificate")


if __name__ == "__main__":
    main()
