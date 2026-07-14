# OPA Spike (Woche 2)

Ziel: Vergleichbarer Mini-Prototyp fuer kontextabhaengige Autorisierungsregeln.

## Use-Cases

1. Ein `PlantOperator` darf den real im Demonstrator vorhandenen Parameter
   `Pump_B_Power` im Rahmen der vorhandenen Mapping-Regel verändern.
2. `Pump_B_Power` muss gemäß `Mapping_Rulesets.xml`, Regel 203, strikt unter
   `16 kW` bleiben.
3. Nur `Admin` darf `manage_users` ausführen.

Die 16-kW-Grenze ist eine im Software-Demonstrator vorhandene
Mapping-Verifikationsregel. Ohne anlagenspezifische Gefährdungsanalyse und
unabhängige Safety-Funktion ist sie **kein Nachweis funktionaler Sicherheit**.

## Dateien

- `policy.rego`: OPA-Regeln
- `policy_test.rego`: ausführbare Positiv-, Grenzwert- und Negativtests
- `system_api_authz.rego`: fail-closed OPA-API-Policy; nur die mTLS-Identität der
  Interface-Partition darf den Gateway-Entscheidungspfad per POST auswerten
- `system_api_authz_test.rego`: Positiv- und Negativtests für Identität, Pfad und Methode
- `inputs/*.json`: Testfaelle
- `run_spike.sh`: Auswertung der Testfaelle gegen die Policy

## Ausfuehrung

```bash
bash run_spike.sh
```

Wenn `opa` nicht installiert ist, endet das Skript mit einem Fehlercode. Ein
fehlendes Prüfwerkzeug darf in der Evaluation nicht als bestandener Test gelten.

Der versionierte Standard-Compose startet OPA ausschließlich über TLS~1.3 mit
Client-Zertifikatspflicht. `tests/e2e/run.sh` prüft den legitimen Interface-Aufruf, die
TLS-Ablehnung ohne Client-Zertifikat und die API-Ablehnung eines gültigen, aber dienstfremden
CPC-Zertifikats. Dieser Nachweis gilt für den Compose-Stand; die Zielplattform benötigt die
separate Transferabnahme unter `tests/transfer/`.

## Erwartete Entscheidungstendenz

- `case1_operator_pump_within_limit.json` -> `allow = true`
- `case2_operator_pump_at_limit.json` -> `allow = false`, `deny_reason` enthält Grenzwert-Hinweis
- `case3_admin_manage_users.json` -> `allow = true`
- `case4_operator_manage_users_denied.json` -> `allow = false`, `deny_reason` enthaelt Admin-Hinweis
