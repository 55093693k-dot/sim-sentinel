param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [string]$LogFile = ""
)
# toast.ps1 -- zero-dependency Windows toast (PowerShell 5.1 + WinRT).
#
# The message is read from a UTF-8 FILE because PS 5.1 mangles non-ASCII
# *arguments* (files are safe, argv is not).
#   line 1     = title
#   line 2..n  = body
# Exits 0 on success, 1 on failure; appends one line to -LogFile when given.
$ErrorActionPreference = 'Stop'
try {
    $lines = @(Get-Content -Path $TextFile -Encoding UTF8)
    if ($lines.Count -ge 1) { $title = [string]$lines[0] } else { $title = 'Simulation' }
    if ($lines.Count -ge 2) { $body = ($lines[1..($lines.Count - 1)] -join "`n") } else { $body = '' }
    if ([string]::IsNullOrWhiteSpace($body)) { $body = ' ' }

    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

    $tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $nodes = $tpl.GetElementsByTagName('text')
    $nodes.Item(0).AppendChild($tpl.CreateTextNode($title)) | Out-Null
    $nodes.Item(1).AppendChild($tpl.CreateTextNode($body)) | Out-Null

    $toast = New-Object Windows.UI.Notifications.ToastNotification $tpl

    # AUMID of the built-in Windows PowerShell: present on every Windows install,
    # so no app registration / no manifest / no shortcut is needed.
    $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)

    if ($LogFile) {
        ("OK`t" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "`t" + $title) |
            Add-Content -Path $LogFile -Encoding UTF8
    }
    exit 0
} catch {
    if ($LogFile) {
        ("FAIL`t" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "`t" + $_.Exception.Message) |
            Add-Content -Path $LogFile -Encoding UTF8
    }
    exit 1
}
