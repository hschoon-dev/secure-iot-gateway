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

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2025-12-22 12:00:00"
    echo "Setze Admin-Passwort... DEV!"
    export ADMIN_PASSWORD="SuperDuperRandomPassword2025"

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

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2025-12-22 12:00:00"

    python3 -m grpc_tools.protoc -I ./grpc_json_handler/proto --python_out=. --grpc_python_out=. ./grpc_json_handler/proto/*.proto

    ls
    python3 main.py
}

vm123() {
    echo "Starte Konfiguration für die ELinOS-Partition Nr.3 - IP: 192.168.0.123"
    echo "Funktion: CPC-Interface, Datenaggregator"
    echo "Code-Verzeichnis: /src/cpc-partition"
    cd /src/cpc-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2025-12-22 12:00:00"

    python3 -m grpc_tools.protoc -I ./grpc_sender/proto --python_out=. --grpc_python_out=. ./grpc_sender/proto/*.proto

    ls
    python3 main.py
}

vm124() {
    echo "Starte Konfiguration für die VoR-1-Partition - IP: 192.168.0.124"
    echo "Funktion: Verification of Request"
    echo "Code-Verzeichnis: /src/intermediate-vor-partition"
    echo "TODO: Yuanchen"
    #cd /src/cpc-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2025-12-22 12:00:00"

    #python3 -m grpc_tools.protoc -I ./grpc_sender/proto --python_out=. --grpc_python_out=. ./grpc_sender/proto/*.proto

    #ls
    #python3 main.py
}

vm125() {
    echo "Starte Konfiguration für die VoR-3-Partition - IP: 192.168.0.125"
    echo "Funktion: Verification of Request Part 2"
    echo "Code-Verzeichnis: /src/intermediate-vor-partition-cpc"
    echo "TODO: Yuanchen"
    #cd /src/cpc-partition

    echo "Setze Systemzeit... WORKAROUND!"
    date -s "2025-12-22 12:00:00"

    #python3 -m grpc_tools.protoc -I ./grpc_sender/proto --python_out=. --grpc_python_out=. ./grpc_sender/proto/*.proto

    #ls
    #python3 main.py
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
    192.168.0.124)
        vm124
        ;;
    192.168.0.125)
        vm125
        ;;
    *)
        default_vm
        ;;
esac