FROM python:3.12

WORKDIR /probe
RUN pip install --no-cache-dir \
    grpcio==1.75.1 \
    grpcio-tools==1.75.1 \
    protobuf==6.32.1

COPY intermediate-vor-partition/grpc_request_handler/proto/request.proto ./proto/
COPY intermediate-vor-partition-cpc/proto/pipeline.proto ./proto/
COPY cpc-partition/grpc_sender/proto/jsontransfer.proto ./proto/
RUN python -m grpc_tools.protoc \
    -I ./proto \
    -I /usr/local/lib/python3.12/site-packages/grpc_tools/_proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/*.proto

COPY tests/e2e/wrong_identity_probe.py ./wrong_identity_probe.py
ENTRYPOINT ["python", "/probe/wrong_identity_probe.py"]
