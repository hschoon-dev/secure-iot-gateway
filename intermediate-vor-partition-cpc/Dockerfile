FROM python:3.11

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto ./proto
RUN python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/*.proto

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]
