FROM python:3.11

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG REQUEST_TYPE
ENV REQUEST_TYPE=$REQUEST_TYPE

# Die Interface Partition als depency für den Fuzzer setzen reicht nicht
# also einfach ein 10 Sekunden delay eingefügt...
CMD [ "/bin/bash", "-c", \
      "sleep 10 && \
       python3 opcua_fuzzer.py \
       --target_host_ip 192.168.156.12 \
       --target_host_port 4840 \
       --target_app_name asyncua \
       --request_opcua_to_fuzz $REQUEST_TYPE"]