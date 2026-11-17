<# PB Gas Control - remove tarefa e firewall. Os DADOS em %ProgramData%\PB Gas Control são preservados. #>
$ErrorActionPreference = 'Continue'
$TaskName = 'PB Gas Control'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Get-Process -Name 'pbgas-server' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-NetFirewallRule -DisplayName 'PB Gas Control (rede local)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
exit 0
