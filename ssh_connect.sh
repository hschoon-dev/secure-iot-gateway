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

# Wird dieses Skript als "worker" für einen einzelnen Host aufgerufen?
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
    # Tab offen lassen nach Verbindungsende
    exec bash
    exit 0
fi

# Hauptaufruf: ein gnome-terminal mit einem Tab pro Host öffnen
SCRIPT=$(realpath "$0")

TAB_ARGS=()
for i in "${!HOSTS[@]}"; do
    index=$((i + 1))
    host="${HOSTS[$i]}"
    TAB_ARGS+=(--tab --title="$host" -- bash -c "\"$SCRIPT\" --probe \"$host\" $index")
done

gnome-terminal "${TAB_ARGS[@]}"