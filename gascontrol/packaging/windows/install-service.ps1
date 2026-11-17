<#
  PB Gas Control - registra o servidor para iniciar com o Windows (executado pelo instalador, como administrador).
  * Pasta de dados restrita a SYSTEM e Administradores (contém JWT_SECRET e a senha inicial).
  * Tarefa agendada no boot, conta SYSTEM, sem limite de tempo, reinício automático em falha.
  * Regra de firewall opcional apenas para perfis Domínio/Privado (nunca rede Pública).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [Parameter(Mandatory = $true)][string]$AdminEmail,
    [switch]$OpenFirewall
)
$ErrorActionPreference = 'Stop'
$TaskName = 'PB Gas Control'
$RuleName = 'PB Gas Control (rede local)'

if ($AdminEmail -notmatch '^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$' -or $AdminEmail.Length -gt 254) {
    throw "E-mail do administrador inválido"
}
$exe = Join-Path $InstallDir 'pbgas-server.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Executável não encontrado: $exe" }

$data = Join-Path $env:ProgramData 'PB Gas Control'
New-Item -ItemType Directory -Force -Path $data | Out-Null
& icacls.exe $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Falha ao restringir permissões da pasta de dados" }

$cfg = Join-Path $data 'config.env'
if (-not (Test-Path -LiteralPath $cfg)) {
    # Primeira instalação. Em atualizações a configuração existente é preservada.
    $content = "PORT=$Port`r`nADMIN_EMAIL=$AdminEmail`r`n"
    [System.IO.File]::WriteAllText($cfg, $content, (New-Object System.Text.UTF8Encoding($false)))
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute $exe -Argument 'serve' -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'PB Tecnologia - PB Gas Control (servidor)' | Out-Null

Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($OpenFirewall) {
    $effectivePort = $Port
    $line = Select-String -LiteralPath $cfg -Pattern '^\s*PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($line) { $effectivePort = [int]$line.Matches[0].Groups[1].Value }
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $effectivePort -Program $exe -Profile Domain, Private | Out-Null
}

Start-ScheduledTask -TaskName $TaskName

$effective = $Port
$m = Select-String -LiteralPath $cfg -Pattern '^\s*PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
if ($m) { $effective = [int]$m.Matches[0].Groups[1].Value }
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:$effective/ready"
        if ($r.StatusCode -eq 200) { Write-Output "Servidor ativo na porta $effective"; exit 0 }
    } catch { Start-Sleep -Seconds 2 }
}
throw "O servidor não respondeu em 90 s. Veja $data\logs\pbgas.log"
