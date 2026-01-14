FROM python:3.11

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the proto directory first (for faster rebuilds when proto changes)
COPY grpc_sender/proto ./grpc_sender/proto

# Generate Python gRPC code from .proto files
RUN python -m grpc_tools.protoc \
    -I ./grpc_sender/proto \
    --python_out=. \
    --grpc_python_out=. \
    ./grpc_sender/proto/*.proto

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]
