FROM python:3.11

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the proto directory first (for faster rebuilds when proto changes)
COPY grpc_request_handler/proto ./grpc_request_handler/proto
COPY mapped_request_client/proto ./mapped_request_client/proto

# Generate Python gRPC code from .proto files
RUN python -m grpc_tools.protoc \
    -I ./grpc_request_handler/proto \
    --python_out=. \
    --grpc_python_out=. \
    ./grpc_request_handler/proto/*.proto

# Generate Python gRPC code for the mapped-request client stub (used to
# forward mapped requests to intermediate-vor-partition-cpc)
RUN python -m grpc_tools.protoc \
    -I ./mapped_request_client/proto \
    --python_out=. \
    --grpc_python_out=. \
    ./mapped_request_client/proto/*.proto

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]