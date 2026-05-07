#!/bin/bash
 
# SSH-Hosts in Bootreihenfolge
HOSTS=(
    "root@192.168.178.114"
    "root@192.168.178.112"
    "root@192.168.178.113"
    "root@192.168.178.115"
    "root@192.168.178.116"
)
 
RETRY_INTERVAL=5  # Sekunden zwischen den Versuchen
SSH_OPTS="-o ConnectTimeout=3 -o StrictHostKeyChecking=no -o BatchMode=yes"
 
probe_and_connect() {
    local host="$1"
    local index="$2"
 
    echo "[$index/5] Warte auf $host ..."
 
    while true; do
        if ssh $SSH_OPTS "$host" exit 2>/dev/null; then
            echo "[$index/5] $host ist erreichbar — verbinde..."
 
            # Neuen Tab im GNOME Terminal öffnen und SSH starten
            gnome-terminal --tab --title="$host" -- bash -c "ssh $SSH_OPTS -o BatchMode=no $host; exec bash"
            return 0
        fi
        sleep $RETRY_INTERVAL
    done
}
 
# Jeden Host in einem eigenen Hintergrundprozess proben
for i in "${!HOSTS[@]}"; do
    index=$((i + 1))
    probe_and_connect "${HOSTS[$i]}" "$index" &
done
 
wait