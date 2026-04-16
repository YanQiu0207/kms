param(
    [ValidateSet("all", "kms", "obs-local")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"

function Get-TaskDefinitions {
    return @(
        @{
            Key = "kms"
            TaskName = "mykms-start-kms"
        },
        @{
            Key = "obs-local"
            TaskName = "mykms-start-obs-local"
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

$taskResults = @()
foreach ($definition in (Resolve-Definitions -Definitions (Get-TaskDefinitions) -Target $Target)) {
    $existingTask = Get-ScheduledTask -TaskName $definition.TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existingTask) {
        $taskResults += [pscustomobject]@{
            task_name = $definition.TaskName
            status = "not_found"
        }
        continue
    }

    Unregister-ScheduledTask -TaskName $definition.TaskName -Confirm:$false
    $taskResults += [pscustomobject]@{
        task_name = $definition.TaskName
        status = "removed"
    }
}

[pscustomobject]@{
    status = "completed"
    target = $Target
    tasks = $taskResults
} | ConvertTo-Json -Depth 5
