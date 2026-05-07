#!/bin/bash

# SSH-Hosts in Bootreihenfolge
HOSTS=(
    "root@192.168.178.114"
    "root@192.168.178.112"
    "root@192.168.178.113"
    "root@192.168.178.115"
    "root@192.168.178.116"
)

RETRY_INTERVAL=5
SSH_OPTS="-o ConnectTimeout=3 -o StrictHostKeyChecking=no"

# Worker-Modus für einen einzelnen SSH-Host
if [[ "$1" == "--probe" ]]; then
    host="$2"
    index="$3"
    echo "[$index/5] Warte auf $host ..."
    while true; do
        if ssh $SSH_OPTS -o BatchMode=yes "$host" exit 2>/dev/null; then
            echo "[$index/5] $host erreichbar — verbinde..."
            ssh $SSH_OPTS "$host"
            echo "--- Verbindung zu $host getrennt ---"
            break
        fi
        sleep $RETRY_INTERVAL
    done
    exec bash
    exit 0
fi

# Hauptaufruf: gnome-terminal mit minicom-Tab zuerst, dann ein Tab pro SSH-Host
SCRIPT=$(realpath "$0")

TAB_ARGS=()

# Erster Tab: minicom
TAB_ARGS+=(--tab --title="minicom /dev/ttyUSB0" -- bash -c "sudo minicom -b 115200 -o -D /dev/ttyUSB0; exec bash")

# Weitere Tabs: ein Tab pro SSH-Host
for i in "${!HOSTS[@]}"; do
    index=$((i + 1))
    host="${HOSTS[$i]}"
    TAB_ARGS+=(--tab --title="$host" -- bash -c "\"$SCRIPT\" --probe \"$host\" $index")
done

gnome-terminal "${TAB_ARGS[@]}"