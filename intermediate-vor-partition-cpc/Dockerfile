FROM python:3.11

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the proto directory first (for faster rebuilds when proto changes)
COPY mapped_request_server/proto ./mapped_request_server/proto

# Generate Python gRPC code for the mapped-request server (receives mapped
# requests forwarded by intermediate-vor-partition)
RUN python -m grpc_tools.protoc \
    -I ./mapped_request_server/proto \
    --python_out=. \
    --grpc_python_out=. \
    ./mapped_request_server/proto/*.proto

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]