#!/bin/bash

# IP von eth0 auslesen
IP=$(ip -4 addr show eth0 | awk '/inet / {print $2}' | cut -d/ -f1)

echo "Detected IP: $IP"

### Sub-Funktionen definieren ###

vm121() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.1 - IP: 192.168.0.121"
    echo "Funktion: Gateway-Interface"
    echo "Code-Verzeichnis: /src/interface-partition"

    cd /src/interface-partition
    python3 -m grpc_tools.protoc -I ./grpc_json_handler/proto --python_out=. --grpc_python_out=. ./grpc_json_handler/proto/*.proto
    python3 -m grpc_tools.protoc -I ./grpc_request_handler/proto --python_out=. --grpc_python_out=. ./grpc_request_handler/proto/*.proto

    ls
    python3 main.py
}

vm122() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.2 - IP: 192.168.0.122"
    echo "Funktion: psM+O-Partition"
    echo "Code-Verzeichnis: /src/psmo-partition"

    cd /src/psmo-partition
    python3 -m grpc_tools.protoc -I ./grpc_json_handler/proto --python_out=. --grpc_python_out=. ./grpc_json_handler/proto/*.proto

    ls
    python3 main.py
}

vm123() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.3 - IP: 192.168.0.123"
    echo "Funktion: CPC-Interface, Datenaggregator"
    echo "Code-Verzeichnis: /src/cpc-partition"

    cd /src/cpc-partition
    python3 -m grpc_tools.protoc -I ./grpc_sender/proto --python_out=. --grpc_python_out=. ./grpc_sender/proto/*.proto

    ls
    python3 main.py
}

default_vm() {
    echo "Unknown IP, using default configuration"
}

### Auswahl basierend auf IP ###
case "$IP" in
    192.168.0.121)
        vm121
        ;;
    192.168.0.122)
        vm122
        ;;
    192.168.0.123)
        vm123
        ;;
    *)
        default_vm
        ;;
esac
