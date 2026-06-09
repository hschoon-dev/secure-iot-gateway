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

# Windows Terminal erwartet Tab-Trennzeichen als eigenes Argument: ";"
# Jeder Tab-Block: new-tab --title "..." -- pwsh -NoExit -File "skript" --probe "host" N total
#
# Der erste Tab wird OHNE "new-tab" angegeben (implizites erstes Tab von wt.exe).
# Alle weiteren Tabs bekommen ";" "new-tab" vorangestellt.

$wtArgs = [System.Collections.Generic.List[string]]::new()

for ($i = 0; $i -lt $Hosts.Count; $i++) {
    $sshHost = $Hosts[$i]
    $index   = $i + 1

    if ($i -gt 0) {
        # Semikolon muss als eigenständiges Argument übergeben werden
        $wtArgs.Add(";")
        $wtArgs.Add("new-tab")
    }

    $wtArgs.Add("--title")
    $wtArgs.Add($sshHost)
    $wtArgs.Add("--")
    $wtArgs.Add("powershell.exe")
    $wtArgs.Add("-NoExit")
    $wtArgs.Add("-ExecutionPolicy")
    $wtArgs.Add("Bypass")
    $wtArgs.Add("-File")
    $wtArgs.Add($scriptPath)
    $wtArgs.Add("--probe")
    $wtArgs.Add($sshHost)
    $wtArgs.Add("$index")
    $wtArgs.Add("$total")
}

Write-Host "Starte Windows Terminal mit $total SSH-Tabs..." -ForegroundColor Cyan
Start-Process wt.exe -ArgumentList $wtArgs