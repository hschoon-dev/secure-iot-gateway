# Runtime-Issues & Retrospektive (2026-03-26)

Diese Datei dokumentiert die aufgetretenen Probleme vom 26.03.2026,
inkl. Ursachen, Fix-Status und Verbesserungen mit Fokus auf macOS.

## A) Technische Laufzeitprobleme im System

| ID | Problem | Beobachtung | Ursache (vermutet/bestätigt) | Status |
|---|---|---|---|---|
| R-001 | `central-mo-client` konnte nicht verbinden | `BadCertificateTimeInvalid` bei OPC UA Session-Aufbau | `mo_client` Zertifikat war abgelaufen (gültig bis 2026-02-19) | Behoben |
| R-002 | gRPC Weiterleitung `interface -> intermediate-vor` fehlschlägt | `Peer name grpc-server is not in peer certificate` | Default `VOR_GRPC_SERVER_NAME` war auf `grpc-server`, SAN enthält `intermediate-vor-partition` | Behoben |
| R-003 | CPC Modbus Reconnect-Fehler | `Reconnection to 192.168.156.20 failed` | Demo-Config zeigte auf nicht vorhandene Ziel-IP im Compose-Setup | Behoben |
| R-004 | CPC OPC UA Fehler bei S7 Endpunkt | Reconnect/Fehler zu `opc.tcp://192.168.156.19:4840` | S7-Endpunkt ist im Docker-Demo nicht vorhanden | Behoben |
| R-005 | Kurzzeitige gRPC `UNAVAILABLE` von CPC zu Interface | `connect: Connection refused (111)` auf `192.168.156.12:50051` | trat während Interface-Recreate auf (transient) | Behoben (transient) |
| R-006 | `docker compose` Warnung bei manuellen Commands | `ADMIN_PASSWORD variable is not set` | Shell-Umgebung bei einigen `docker compose` Befehlen ohne Export | Offen (niedrige Priorität) |
| R-007 | CPC meldet regelmäßig OPC-UA-Zertifikats-/Disconnect-Warnungen | `certificate does not contain the hostname in DNSNames ...` + `Disconnected from opc.tcp://192.168.156.18:4840/freeopcua/server/` | Zertifikat-/Hostname-Mismatch und/oder connect-per-request Verhalten im Client | Offen (beobachten) |
| R-008 | CPC loggt `update_endpoints` auf ERROR-Level trotz HTTP 200 | `update_endpoints called with data: ...` als ERROR | Vermutlich falsches Log-Level statt Funktionsfehler | Offen (Codequalität) |

## B) Prozess- und Umgebungsprobleme im Verlauf (für die Arbeit)

| ID | Thema | Beobachtung | Auswirkung |
|---|---|---|---|
| P-001 | Docker-Zugriff im Arbeitskontext | `permission denied while trying to connect to the docker API` ohne Freigabe | Verzögerte Diagnose/Verifikation bis Rechte eskaliert wurden |
| P-002 | Fehlende Standard-Umgebungsdatei | Keine `.env`/`.env.example` im Projektroot | Höheres Risiko für inkonsistente Starts und Warnmeldungen |
| P-003 | Readiness vs. Running | Container waren `Up`, aber einzelne Verbindungen während Recreate kurzzeitig nicht erreichbar | Transiente Fehler, obwohl kein echter Dauerdefekt vorlag |
| P-004 | Logsignal-Rauschen | Fachlich normale Calls wurden teils als ERROR protokolliert | Erschwerte Fehleranalyse und falsche Priorisierung |

## C) macOS-spezifische Hürden

| ID | Thema | Beobachtung | Verbesserungsbedarf |
|---|---|---|---|
| M-001 | OPC-UA Client-Zertifikate (UaExpert/macOS) | Zugriff klappt nur, wenn Client-Zertifikat im Truststore des Servers liegt | Automatisierter Import-Workflow für macOS fehlt |
| M-002 | Endpoint-Verwechslung Host vs. Docker-Netz | Intern wird `interface-partition` genutzt, extern auf Mac `localhost:4840` | Dokumentation muss intern/extern klar trennen |
| M-003 | Zertifikats-Hostname/SAN | Hostname-SAN passt nicht immer zum tatsächlich verwendeten Zielnamen | Zertifikatsstrategie für `localhost` + Service-Namen vereinheitlichen |
| M-004 | Secret-Handling beim lokalen Start | `ADMIN_PASSWORD` muss konsistent exportiert sein | macOS-Startskript mit vorvalidierten Variablen fehlt |

## D) Verbesserungen für die nächste Iteration (macOS-ready)

1. `./scripts/start_local.sh` einführen, das `ADMIN_PASSWORD` prüft/lädt und Compose robust startet.
2. `.env.example` mit Pflichtvariablen (`ADMIN_PASSWORD`, optional `INTERFACE_OPCUA_URL`) ergänzen.
3. `docs/macos-opcua-quickstart.md` erstellen (UaExpert-Setup, Endpoint, SecurityPolicy, Zertifikatsimport).
4. Zertifikate mit SANs für `localhost`, `interface-partition` und relevante IP/DNS-Namen standardisieren.
5. Compose-`healthcheck` für zentrale Services ergänzen und Abhängigkeiten auf `service_healthy` umstellen.
6. Logging-Level bereinigen (`update_endpoints` von ERROR auf INFO/DEBUG), um False-Positives zu reduzieren.

## E) Heute umgesetzte Fixes

1. OPC-UA Client-Zertifikat `mo_client` neu ausgestellt und Trust im Interface aktualisiert.
2. gRPC-Default im Interface angepasst: Servername wird jetzt aus `TARGET_HOST` abgeleitet.
3. Modbus-Demo-Config korrigiert: nicht erreichbare IP `192.168.156.20` auf Compose-IP `192.168.156.181` umgestellt.
4. S7-1200 Block aus Docker-Demo-OPC-UA-Config entfernt (nicht vorhandener Demo-Endpunkt).

## F) Finale Verifikation (26.03.2026, 00:50 CET)

1. `docker ps` / `docker compose ps`: alle Partitionen `Up`.
2. Interface-Logs: kein erneuter `Peer name grpc-server is not in peer certificate` Fehler; stattdessen gRPC ACKs.
3. Keine Reconnect-Spam-Fehler mehr zu `192.168.156.20` oder `192.168.156.19`.
4. End-to-End-Verarbeitung sichtbar (`central-mo-client` -> `interface-partition` -> `intermediate-vor-partition` -> `cpc-partition`).
