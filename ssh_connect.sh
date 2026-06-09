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

# ──────────────────────────────────────────────────────────────────────────────
# Worker-Modus: wird von jedem Tab-Kindprozess aufgerufen
# ──────────────────────────────────────────────────────────────────────────────
if [[ "$1" == "--probe" ]]; then
    host="$2"
    index="$3"
    total="$4"
    echo -e "\e[36m[$index/$total] Warte auf $host ...\e[0m"
    while true; do
        if ssh $SSH_OPTS -o BatchMode=yes "$host" exit 2>/dev/null; then
            echo -e "\e[32m[$index/$total] $host erreichbar — verbinde...\e[0m"
            ssh $SSH_OPTS "$host"
            echo -e "\e[33m--- Verbindung zu $host getrennt ---\e[0m"
            break
        fi
        sleep $RETRY_INTERVAL
    done
    echo "Drücke Enter zum Schliessen..."
    read
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# Hauptaufruf: gnome-terminal mit einem Tab pro SSH-Host
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT=$(realpath "$0")
TOTAL=${#HOSTS[@]}

if ! command -v gnome-terminal &>/dev/null; then
    echo "Fehler: gnome-terminal nicht gefunden." >&2
    exit 1
fi

# Alle Tabs als separater gnome-terminal-Aufruf aufbauen.
# Wichtig: jedes --tab bekommt sein eigenes bash -c '...' mit einfachen Quotes,
# damit kein Quoting-Problem durch verschachtelte Anführungszeichen entsteht.
ARGS=()
for i in "${!HOSTS[@]}"; do
    index=$((i + 1))
    host="${HOSTS[$i]}"
    ARGS+=(
        --tab
        --title="$host"
        --
        bash -c "'$SCRIPT' --probe '$host' $index $TOTAL; exec bash"
    )
done

gnome-terminal "${ARGS[@]}"