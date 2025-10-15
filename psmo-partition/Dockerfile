FROM python:3.12

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the proto directory first (for faster rebuilds when proto changes)
COPY psmo_shm_handler/proto ./psmo_shm_handler/proto

# Generate Python gRPC code from .proto files
RUN python -m grpc_tools.protoc \
    -I ./psmo_shm_handler/proto \
    --python_out=. \
    --grpc_python_out=. \
    ./psmo_shm_handler/proto/*.proto

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]

