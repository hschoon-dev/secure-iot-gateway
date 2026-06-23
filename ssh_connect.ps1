#Requires -Version 5.1
<#
.SYNOPSIS
    Öffnet Windows Terminal mit einem Tab pro SSH-Host.
    Jeder Tab wartet in einer Retry-Schleife, bis der Host per SSH erreichbar ist,
    verbindet sich dann automatisch und bleibt nach Trennung offen.

.NOTES
    Voraussetzungen:
      - Windows Terminal (wt.exe): winget install Microsoft.WindowsTerminal
      - OpenSSH-Client (Windows 10/11 eingebaut):
        Einstellungen > Apps > Optionale Features > OpenSSH-Client
#>

# ──────────────────────────────────────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────────────────────────────────────

$Hosts = @(
    "root@192.168.178.114",
    "root@192.168.178.112",
    "root@192.168.178.113",
    "root@192.168.178.115",
    "root@192.168.178.116"
)

$RetryInterval = 5   # Sekunden zwischen SSH-Verbindungsversuchen

# ──────────────────────────────────────────────────────────────────────────────
# Worker-Modus: wird von jedem Tab-Kindprozess aufgerufen
# ──────────────────────────────────────────────────────────────────────────────

if ($args[0] -eq "--probe") {
    $sshHost = $args[1]
    $index   = $args[2]
    $total   = $args[3]

    Write-Host "[$index/$total] Warte auf $sshHost ..." -ForegroundColor Cyan

    $sshTest = @("-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes")
    $sshConn = @("-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no")

    while ($true) {
        & ssh @sshTest $sshHost exit 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[$index/$total] $sshHost erreichbar — verbinde..." -ForegroundColor Green
            & ssh @sshConn $sshHost
            Write-Host "--- Verbindung zu $sshHost getrennt ---" -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds $RetryInterval
    }

    Write-Host "Drücke eine Taste zum Schliessen..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Hauptaufruf: Windows Terminal mit einem Tab pro SSH-Host starten
# ──────────────────────────────────────────────────────────────────────────────

if (-not (Get-Command wt.exe -ErrorAction SilentlyContinue)) {
    Write-Error "Windows Terminal (wt.exe) nicht gefunden.`nInstallieren: winget install Microsoft.WindowsTerminal"
    exit 1
}

$scriptPath = $MyInvocation.MyCommand.Path
$total      = $Hosts.Count

# ──────────────────────────────────────────────────────────────────────────────
# WICHTIG: wt.exe hat eine eigene, an ';' und '--' orientierte Mini-Grammatik.
# Start-Process -ArgumentList mit einem String[]-Array lässt PowerShell die
# Elemente selbst wieder zu EINER Kommandozeile zusammenbauen — dabei können
# ';' und '--' verrutschen oder falsch gequotet werden, was genau dazu führt,
# dass Tabs fehlen, verschmelzen oder in separaten Fenstern aufgehen.
#
# Lösung: die komplette Kommandozeile selbst als EINEN fertig gequoteten
# String bauen, exakt so, wie man sie auch interaktiv eingeben würde.
# Für jeden Host wird "new-tab" explizit gesetzt (auch für den ersten Tab),
# damit es keine Mehrdeutigkeit bei der impliziten Default-Aktion gibt.
# ──────────────────────────────────────────────────────────────────────────────

$segments = [System.Collections.Generic.List[string]]::new()

for ($i = 0; $i -lt $Hosts.Count; $i++) {
    $sshHost = $Hosts[$i]
    $index   = $i + 1

    $segment = "new-tab --title `"$sshHost`" -- powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" --probe `"$sshHost`" $index $total"
    $segments.Add($segment)
}

$cmdLine = $segments -join " ; "

Write-Host "Starte Windows Terminal mit $total SSH-Tabs..." -ForegroundColor Cyan
Write-Host "wt-Kommandozeile: $cmdLine" -ForegroundColor DarkGray

Start-Process -FilePath "wt.exe" -ArgumentList $cmdLine