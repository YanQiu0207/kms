param(
    [ValidateSet("all", "kms", "obs-local")]
    [string]$Target = "all",
    [ValidateSet("startup", "logon")]
    [string]$TriggerMode = "startup"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-CurrentUserId {
    if ($env:USERDOMAIN) {
        return "$($env:USERDOMAIN)\$($env:USERNAME)"
    }

    return $env:USERNAME
}

function Get-TaskDefinitions {
    param(
        [string]$RepoRoot
    )

    return @(
        @{
            Key = "kms"
            TaskName = "mykms-start-kms"
            ScriptPath = Join-Path $RepoRoot "scripts\start_kms.py"
            Description = "Start mykms kms-api in background at Windows startup."
        },
        @{
            Key = "obs-local"
            TaskName = "mykms-start-obs-local"
            ScriptPath = Join-Path $RepoRoot "scripts\start_obs_local.py"
            Description = "Start mykms obs-local backend and frontend at Windows startup."
        }
    )
}

function Resolve-Definitions {
    param(
        [array]$Definitions,
        [string]$Target
    )

    if ($Target -eq "all") {
        return $Definitions
    }

    return @($Definitions | Where-Object { $_.Key -eq $Target })
}

$repoRoot = Get-RepoRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python runtime was not found: $pythonPath"
}

$userId = Get-CurrentUserId
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

if ($TriggerMode -eq "startup") {
    if (-not (Test-IsAdministrator)) {
        throw "Installing startup tasks requires an elevated PowerShell session because the tasks run as SYSTEM."
    }
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $principalLabel = "SYSTEM"
    $triggerLabel = "AtStartup"
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $principalLabel = $userId
    $triggerLabel = "AtLogOn"
}

$taskResults = @()
foreach ($definition in (Resolve-Definitions -Definitions (Get-TaskDefinitions -RepoRoot $repoRoot) -Target $Target)) {
    if (-not (Test-Path -LiteralPath $definition.ScriptPath)) {
        throw "Startup script was not found: $($definition.ScriptPath)"
    }

    $action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"{0}"' -f $definition.ScriptPath)
    $existingTask = Get-ScheduledTask -TaskName $definition.TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask) {
        Unregister-ScheduledTask -TaskName $definition.TaskName -Confirm:$false
    }

    $null = Register-ScheduledTask `
        -TaskName $definition.TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $definition.Description `
        -Force

    $taskResults += [pscustomobject]@{
        task_name = $definition.TaskName
        script_path = $definition.ScriptPath
        python_path = $pythonPath
        principal = $principalLabel
        trigger = $triggerLabel
        status = "installed"
    }
}

[pscustomobject]@{
    status = "installed"
    target = $Target
    trigger_mode = $TriggerMode
    repo_root = $repoRoot
    tasks = $taskResults
} | ConvertTo-Json -Depth 5
