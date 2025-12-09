#!/usr/bin/env bash
set -euo pipefail
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Shebang: Führt das Skript explizit mit der Bash aus (unabhängig von /bin/sh).
# set -e  : Skript bricht sofort ab, wenn ein Befehl mit einem Fehlercode (!=0)
#           endet. Verhindert, dass Fehler “übersehen” werden.
# set -u  : Verwendung einer nicht gesetzten Variable führt zu einem Fehler.
#           Hilft, Tippfehler oder fehlende Umgebungsvariablen früh zu erkennen.
# set -o pipefail :
#           Wenn ein Befehl in einer Pipe fehlschlägt, gilt die gesamte Pipe als
#           fehlgeschlagen (nicht nur der letzte Befehl). Erhöht die Robustheit.

# Basis-Verzeichnis (Root des Projekts)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Ermittelt das Verzeichnis, in dem dieses Skript liegt, unabhängig davon,
# von wo aus es aufgerufen wird:
# - dirname "${BASH_SOURCE[0]}" : Das Verzeichnis der Skriptdatei.
# - cd ... && pwd               : wechselt in dieses Verzeichnis und gibt den
#                                 absoluten Pfad aus.
# Ergebnis: ROOT_DIR zeigt auf das Projekt- / Skript-Root.

CA_DIR="${ROOT_DIR}/ca"
CA_KEY="${CA_DIR}/ca.key"
CA_CRT="${CA_DIR}/ca.crt"
CA_SERIAL="${CA_DIR}/ca.srl"
# Pfade zur lokalen Certificate Authority (CA):
# - CA_KEY    : Private Key der CA (zum Signieren von Zertifikaten).
# - CA_CRT    : Öffentliches CA-Zertifikat (wird von Clients/Servern vertraut).
# - CA_SERIAL : Datei, in der die nächste Seriennummer der CA gespeichert wird.
#               Wird von OpenSSL beim Signieren verwendet.

KEY_BITS=4096
CERT_DAYS=825
# KEY_BITS  : Schlüssellänge für RSA-Schlüssel (4096 Bit = aktuell sicherer Standard).
# CERT_DAYS : Gültigkeitsdauer der ausgestellten Zertifikate in Tagen.
#             825 Tage ist z.B. ein typischer Wert, der innerhalb gängiger
#             Browser-/CA-Einschränkungen liegt.

echo "== gRPC Zertifikats-Generation =="
# Informative Überschrift, damit im Terminal klar ist, was passiert.

# --- CA prüfen -------------------------------------------------------------
# Vor jeglicher Zertifikats-Erstellung wird geprüft, ob eine funktionierende
# CA existiert. Ohne CA kann kein Zertifikat signiert werden.

if [[ ! -f "${CA_KEY}" || ! -f "${CA_CRT}" ]]; then
  echo "FEHLER: CA-Key oder CA-Cert nicht gefunden:"
  echo "  ${CA_KEY}"
  echo "  ${CA_CRT}"
  exit 1
fi
# Überprüft, ob sowohl der private CA-Schlüssel als auch das CA-Zertifikat
# existieren. Falls eine der Dateien fehlt, bricht das Skript mit einer
# aussagekräftigen Fehlermeldung ab.

# Serial-Datei initialisieren (für -CAserial)
if [[ ! -f "${CA_SERIAL}" ]]; then
  echo "01" > "${CA_SERIAL}"
fi
# OpenSSL benötigt eine Seriennummer-Datei, um jedem ausgestellten Zertifikat
# eine eindeutige Seriennummer zu geben.
# - Falls die Datei nicht existiert, wird mit "01" begonnen.
# - OpenSSL inkrementiert diese Nummer bei jeder Signierung automatisch.
# WICHTIG: Die Seriennummer sollte pro CA eindeutig sein; deswegen wird diese
# Datei dauerhaft gepflegt und nicht bei jedem Lauf überschrieben.

# --- Helper-Funktionen -----------------------------------------------------
# Ab hier: Funktionen, um Server- und Client-Zertifikate generisch für
# verschiedene Verzeichnisse / Services zu erzeugen.

generate_server_cert() {
  local dir="$1"
  local name="${2:-server}"   # default: server
  # Parameter:
  # - $1 (dir)  : Zielverzeichnis, in dem Key/CSR/CRT abgelegt werden.
  # - $2 (name) : Basename der Dateien (z.B. "server"); Default = "server".

  local cnf="${dir}/${name}.cnf"
  local key="${dir}/${name}.key"
  local csr="${dir}/${name}.csr"
  local crt="${dir}/${name}.crt"
  # Zu jedem Namen gehören:
  # - .cnf : OpenSSL-Konfigurationsdatei, die Subject, SAN, Extensions etc. definiert.
  # - .key : privater Schlüssel.
  # - .csr : Certificate Signing Request, der vom Key abgeleitet wird.
  # - .crt : das signierte Zertifikat.

  echo ""
  echo "-- Server-Zertifikat in ${dir} (${name}) --"

  if [[ ! -f "${cnf}" ]]; then
    echo "  Übersprungen: Config ${cnf} nicht gefunden."
    return 0
  fi
  # Ohne passende Konfigurationsdatei kann kein korrektes Server-Zertifikat
  # mit SAN/Extensions erzeugt werden, daher wird in diesem Fall nur
  # informiert und die Funktion sauber beendet (kein Fehler!).

  # Wenn Zertifikat schon existiert: nichts tun (idempotent)
  if [[ -f "${crt}" ]]; then
    echo "  Zertifikat ${crt} existiert bereits – überspringe."
    return 0
  fi
  # Idempotenz: Die Funktion ist so ausgelegt, dass sie mehrfach aufgerufen
  # werden kann, ohne bereits vorhandene Zertifikate zu überschreiben.
  # Das vermeidet unnötige Neugenerierung und potentielle Downtime.

  # Falls alte Fragmente existieren: aufräumen
  if [[ -f "${key}" || -f "${csr}" ]]; then
    echo "  Entferne alte Key/CSR-Fragmente."
    rm -f "${key}" "${csr}"
  fi
  # Sicherheitshalber werden alte, unvollständige oder veraltete Key-/CSR-Dateien
  # gelöscht, damit später wirklich nur die neu generierten Artefakte verwendet
  # werden und es zu keinen Verwechslungen kommt.

  echo "  Generiere Key: ${key}"
  openssl genrsa -out "${key}" "${KEY_BITS}"
  # Generiert einen neuen RSA Private Key:
  # - genrsa       : RSA-Schlüssel erzeugen.
  # - -out ${key}  : Speichert den Key in der angegebenen Datei.
  # - ${KEY_BITS}  : Schlüssellänge (z.B. 4096 Bit).

  echo "  Generiere CSR: ${csr}"
  openssl req -new -key "${key}" -out "${csr}" -config "${cnf}"
  # Erzeugt einen Certificate Signing Request (CSR):
  # - req -new          : Neue CSR anlegen.
  # - -key "${key}"     : Verwendet den vorher generierten privaten Schlüssel.
  # - -out "${csr}"     : Ziel-Datei für die CSR.
  # - -config "${cnf}"  : Nutzt die OpenSSL-Konfigurationsdatei, in der
  #                       u.a. Subject und Extensions (SAN usw.) stehen.

  # Extension-Section aus req_extensions lesen, z.B.
  # req_extensions = v3_req   oder   req_extensions=req_ext
  local ext_section=""
  ext_section=$(
    grep -E '^[[:space:]]*req_extensions[[:space:]]*=' "${cnf}" \
      | head -n1 \
      | cut -d= -f2 \
      | tr -d '[:space:]'
  )
  # Ziel: Herausfinden, welche "Extensions"-Section in der .cnf für das
  # Zertifikat verwendet werden soll (z.B. "v3_req" oder "req_ext").
  # Schritt für Schritt:
  # - grep ... req_extensions = ... : Sucht nach einer Zeile, die die
  #   Option "req_extensions" setzt (ggf. mit Leerzeichen).
  # - head -n1                     : Falls mehrere vorhanden sind, nimm die erste.
  # - cut -d= -f2                  : Nimmt alles nach dem '=' (Name der Section).
  # - tr -d '[:space:]'            : Entfernt Leerzeichen/Tabulatoren um den Namen.

  # Fallback: falls keine req_extensions-Zeile da ist, heuristisch suchen
  if [[ -z "${ext_section}" ]]; then
    if grep -Eq '^[[:space:]]*\[[[:space:]]*req_ext[[:space:]]*\][[:space:]]*$' "${cnf}"; then
      ext_section="req_ext"
    elif grep -Eq '^[[:space:]]*\[[[:space:]]*v3_req[[:space:]]*\][[:space:]]*$' "${cnf}"; then
      ext_section="v3_req"
    fi
  fi
  # Falls keine explizite req_extensions-Zeile gefunden wurde:
  # - Prüft, ob es eine Section [req_ext] gibt -> dann wird diese verwendet.
  # - Sonst, ob es [v3_req] gibt -> dann diese.
  # Diese Heuristik ist nützlich, wenn die Konfigurationsdatei etwas einfacher
  # gehalten ist, aber trotzdem typische Namen nutzt.

  # Optional: prüfen, ob es diese Section wirklich gibt
  if [[ -n "${ext_section}" ]]; then
    if ! grep -Eq "^[[:space:]]*\[[[:space:]]*${ext_section}[[:space:]]*\][[:space:]]*$" "${cnf}"; then
      echo "FEHLER: req_extensions=${ext_section}, aber Section [${ext_section}] existiert nicht in ${cnf}."
      return 1
    fi
  fi
  # Sicherheitscheck: Es wird überprüft, ob tatsächlich eine Section mit dem
  # ermittelten Namen [ext_section] in der .cnf existiert. Falls nicht, wird
  # mit Fehler abgebrochen, statt ein falsches oder "nacktes" Zertifikat ohne
  # nötige Extensions zu erzeugen.

  if [[ -z "${ext_section}" ]]; then
    echo "FEHLER: Konnte keine Extension-Section (req_extensions=..., [req_ext], [v3_req]) in ${cnf} bestimmen."
    echo "       Für Server-Zertifikate (SAN etc.) ist das Pflicht."
    return 1
  fi
  # Wenn selbst nach Heuristik keine passende Section gefunden wurde, bricht
  # die Funktion mit einem klaren Fehler ab. Für Server-Zertifikate sind
  # Extensions wie Subject Alternative Names (SAN) Pflicht, sonst gibt es
  # Probleme mit modernen TLS-Clients/Browern.

  echo "  Signiere Zertifikat: ${crt} (Extensions: ${ext_section})"
  openssl x509 -req \
    -in "${csr}" \
    -CA "${CA_CRT}" \
    -CAkey "${CA_KEY}" \
    -CAserial "${CA_SERIAL}" \
    -out "${crt}" \
    -days "${CERT_DAYS}" \
    -sha256 \
    -extfile "${cnf}" \
    -extensions "${ext_section}"
  # Signiert die CSR mit der lokalen CA:
  # - x509 -req           : Wandelt eine CSR in ein signiertes Zertifikat um.
  # - -in "${csr}"        : Eingabedatei (CSR).
  # - -CA/-CAkey          : CA-Zertifikat und privater CA-Schlüssel.
  # - -CAserial           : Datei mit der Seriennummer der CA.
  # - -out "${crt}"       : Ausgabe-Datei für das fertige Zertifikat.
  # - -days "${CERT_DAYS}": Gültigkeitsdauer in Tagen.
  # - -sha256             : Signatur-Hashfunktion (heutzutage Standard).
  # - -extfile "${cnf}"   : Konfigurationsdatei, aus der die Extensions gelesen
  #                         werden sollen.
  # - -extensions ...     : Name der Section in der .cnf, die die Extensions
  #                         für das Zertifikat enthält (z.B. SAN, KeyUsage).

  echo "  Fertig: ${crt}"
  # Hinweis am Ende, dass die Zertifikatserstellung erfolgreich war.
}

generate_client_cert() {
  local dir="$1"
  local name="${2:-client}"  # default: client
  # Parameter:
  # - $1 (dir)  : Zielverzeichnis für Key/CSR/CRT.
  # - $2 (name) : Basename der Dateien (z.B. "client"); Default = "client".

  local cnf="${dir}/${name}.cnf"
  local key="${dir}/${name}.key"
  local csr="${dir}/${name}.csr"
  local crt="${dir}/${name}.crt"
  # Entspricht der Struktur wie bei Server-Zertifikaten, nur mit anderem Namen.

  echo ""
  echo "-- Client-Zertifikat in ${dir} (${name}) --"

  # Wenn Zertifikat schon existiert: nichts tun (idempotent)
  if [[ -f "${crt}" ]]; then
    echo "  Zertifikat ${crt} existiert bereits – überspringe."
    return 0
  fi
  # Auch hier: Idempotenz. Ein vorhandenes Zertifikat wird nicht automatisch
  # überschrieben, um unerwartete Änderungen an laufenden Systemen zu vermeiden.

  # Alte Fragmente ggf. entfernen
  if [[ -f "${key}" || -f "${csr}" ]]; then
    echo "  Entferne alte Key/CSR-Fragmente."
    rm -f "${key}" "${csr}"
  fi
  # Aufräumen alter Schlüssel/CSRs, um saubere Zustände sicherzustellen.

  echo "  Generiere Key: ${key}"
  openssl genrsa -out "${key}" "${KEY_BITS}"
  # Neuer privater Client-Schlüssel, analog zu Server-Seite.

  if [[ -f "${cnf}" ]]; then
    echo "  Generiere CSR mit Config: ${csr}"
    openssl req -new -key "${key}" -out "${csr}" -config "${cnf}"
    # Falls eine spezifische Konfigurationsdatei existiert (z.B. mit SAN oder
    # Besonderheiten für den Client), wird diese analog zu Server-Zertifikaten
    # verwendet.
  else
    echo "  WARNUNG: ${cnf} nicht gefunden, benutze einfaches Subject."
    openssl req -new -key "${key}" -out "${csr}" -subj "/CN=${name}"
    # Fallback: Wenn keine .cnf vorhanden ist, wird ein sehr einfaches Subject
    # verwendet (nur Common Name).
    # - Dies eignet sich für einfache mTLS-Clients, bei denen lediglich der CN
    #   zur Identifikation ausreicht oder sonstige Details nicht kritisch sind.
  fi

  echo "  Signiere Zertifikat: ${crt}"
  openssl x509 -req \
    -in "${csr}" \
    -CA "${CA_CRT}" \
    -CAkey "${CA_KEY}" \
    -CAserial "${CA_SERIAL}" \
    -out "${crt}" \
    -days "${CERT_DAYS}" \
    -sha256
  # Signiert die Client-CSR mit der CA, ähnlich wie bei Server-Zertifikaten,
  # nur ohne explizite Extensions-Section. Für viele einfache mTLS-Szenarien
  # reicht dies aus, z.B. wenn lediglich ClientAuth und CN relevant sind.

  echo "  Fertig: ${crt}"
  # Bestätigung über das erzeugte Client-Zertifikat.
}

# --- Konkrete Verzeichnisse aufrufen ---------------------------------------
# Ab hier wird die oben definierte Logik auf konkrete Verzeichnisse/
# “Module” angewendet. Jedes Verzeichnis repräsentiert typischerweise einen
# bestimmten Dienst oder Anwendungsbereich im Projekt.

# cpc-certs: nur Client
generate_client_cert "${ROOT_DIR}/cpc-certs" "client"
# Erzeugt (falls nicht vorhanden) ein Client-Zertifikat in:
#   ${ROOT_DIR}/cpc-certs/client.{key,csr,crt}
# Verwendung z.B. für einen bestimmten gRPC-Client (CPC).

# interface-certs: Client + Server
generate_client_cert "${ROOT_DIR}/interface-certs" "client"
generate_server_cert "${ROOT_DIR}/interface-certs" "server"
# In diesem Verzeichnis werden sowohl Client- als auch Server-Zertifikate
# erzeugt. Typischerweise für einen Dienst, der sowohl als Server fungiert,
# aber sich im Rahmen von mTLS gegenüber anderen Services ebenfalls als
# Client authentifizieren muss.

# intermediate-vor-certs: nur Server
generate_server_cert "${ROOT_DIR}/intermediate-vor-certs" "server"
# Erzeugt ein Server-Zertifikat für den Dienst/Komponente "intermediate-vor".

# psmo-certs: nur Server
generate_server_cert "${ROOT_DIR}/psmo-certs" "server"
# Erzeugt ein Server-Zertifikat für den Dienst/Komponente "psmo".

echo ""
echo "== Fertig =="
# Abschlussmeldung, damit im Terminal klar erkennbar ist, dass alle
# Zertifikatsgenerierungen erfolgreich (oder zumindest ohne Abbruch) durchlaufen wurden.
