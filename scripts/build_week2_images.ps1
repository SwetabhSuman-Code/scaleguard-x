param(
    [string]$Registry = "",
    [string]$Tag = "latest",
    [switch]$Push
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Images = @(
    @{ Name = "scaleguard-api"; Dockerfile = "api_gateway/Dockerfile" },
    @{ Name = "scaleguard-ingestion"; Dockerfile = "ingestion_service/Dockerfile" },
    @{ Name = "scaleguard-prediction"; Dockerfile = "prediction_engine/Dockerfile" },
    @{ Name = "scaleguard-worker"; Dockerfile = "worker_cluster/Dockerfile" },
    @{ Name = "scaleguard-autoscaler"; Dockerfile = "autoscaler/Dockerfile" }
)

foreach ($Image in $Images) {
    $LocalTag = "$($Image.Name):$Tag"
    docker build -t $LocalTag -f $Image.Dockerfile .
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed for $LocalTag"
    }

    if ($Registry) {
        $RemoteTag = "$Registry/$($Image.Name):$Tag"
        docker tag $LocalTag $RemoteTag
        if ($LASTEXITCODE -ne 0) {
            throw "Docker tag failed for $RemoteTag"
        }
        if ($Push) {
            docker push $RemoteTag
            if ($LASTEXITCODE -ne 0) {
                throw "Docker push failed for $RemoteTag"
            }
        }
    }
}

Write-Host "Built ScaleGuard week-2 deployment images with tag '$Tag'."
if ($Registry -and -not $Push) {
    Write-Host "Images were tagged for '$Registry' but not pushed. Re-run with -Push after registry login."
}
