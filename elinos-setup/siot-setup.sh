#!/bin/bash

# IP von eth0 auslesen
IP=$(ip -4 addr show eth0 | awk '/inet / {print $2}' | cut -d/ -f1)

echo "Detected IP: $IP"

### Sub-Funktionen definieren ###
vm12() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.1 - IP: 192.168.156.12"
    echo "Funktion: Gateway-Interface"
    echo "Code-Verzeichnis: /src/interface-partition"
    cd /src/interface-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2026-02-12 12:00:00"
    echo "Setze Admin-Passwort... DEV!"
    export ADMIN_PASSWORD="SuperDuperRandomPassword2025"

    python3 -m grpc_tools.protoc -I ./grpc_json_handler/proto --python_out=. --grpc_python_out=. ./grpc_json_handler/proto/*.proto
    python3 -m grpc_tools.protoc -I ./grpc_request_handler/proto --python_out=. --grpc_python_out=. ./grpc_request_handler/proto/*.proto

    ls
    python3 main.py
}

vm13() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.2 - IP: 192.168.156.13"
    echo "Funktion: psM+O-Partition"
    echo "Code-Verzeichnis: /src/psmo-partition"
    cd /src/psmo-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2026-02-12 12:00:00"

    python3 -m grpc_tools.protoc -I ./grpc_json_handler/proto --python_out=. --grpc_python_out=. ./grpc_json_handler/proto/*.proto

    ls
    python3 main.py
}

vm14() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.3 - IP: 192.168.156.14"
    echo "Funktion: CPC-Interface, Datenaggregator"
    echo "Code-Verzeichnis: /src/cpc-partition"
    cd /src/cpc-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2026-02-12 12:00:00"

    python3 -m grpc_tools.protoc -I ./grpc_sender/proto --python_out=. --grpc_python_out=. ./grpc_sender/proto/*.proto

    ls
    python3 main.py
}

vm15() {
    echo "Starte Konfiguration für die VoR-1-Partition - IP: 192.168.156.15"
    echo "Funktion: Verification of Request"
    echo "Code-Verzeichnis: /src/intermediate-vor-partition"
    echo "TODO: Yuanchen"
    cd /src/intermediate-vor-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2026-02-12 12:00:00"

    python3 -m grpc_tools.protoc -I ./grpc_request_handler/proto --python_out=. --grpc_python_out=. ./grpc_request_handler/proto/*.proto

    ls
    python3 main.py
}

vm16() {
    echo "Starte Konfiguration für die VoR-2-Partition - IP: 192.168.156.16"
    echo "Funktion: Verification of Request Part 2"
    echo "Code-Verzeichnis: /src/intermediate-vor-partition-cpc"
    echo "TODO: Yuanchen"
    cd /src/intermediate-vor-partition-cpc

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2026-02-12 12:00:00"

    ls
    python3 main.py
}

default_vm() {
    echo "Unknown IP, using default configuration"
}

### Auswahl basierend auf IP ###
case "$IP" in
    192.168.156.12)
        vm12
        ;;
    192.168.156.13)
        vm13
        ;;
    192.168.156.14)
        vm14
        ;;
    192.168.156.15)
        vm15
        ;;
    192.168.156.16)
        vm16
        ;;
    *)
        default_vm
        ;;
esac