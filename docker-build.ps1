#!/usr/bin/env pwsh
<# 
.SYNOPSIS
Build ScaleGuard X services without BuildKit (fixes Windows Docker Desktop issues)

.DESCRIPTION
Disables Docker BuildKit for compose builds on Windows where context transfer fails.
BuildKit has issues transferring full context in docker-compose on Windows/WSL2.

.EXAMPLE
.\docker-build.ps1 
.\docker-build.ps1 -Service anomaly_engine
.\docker-build.ps1 -NoBuild
#>

param(
    [string]$Service,
    [switch]$NoBuild,
    [switch]$NoPush
)

# Disable BuildKit for docker compose (fixes Windows path issues)
$env:DOCKER_BUILDKIT = 0
$env:COMPOSE_DOCKER_CLI_BUILD = 1

Write-Host "Docker BuildKit disabled for Windows compatibility" -ForegroundColor Cyan
Write-Host "---" -ForegroundColor Cyan

if ($NoBuild) {
    Write-Host "Skipping build (--no-build flag set)" -ForegroundColor Yellow
    exit 0
}

if ($Service) {
    Write-Host "Building service: $Service" -ForegroundColor Green
    docker compose build --no-cache $Service
} else {
    Write-Host "Building all services..." -ForegroundColor Green
    docker compose build --no-cache
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "---" -ForegroundColor Cyan
Write-Host "Build completed successfully" -ForegroundColor Green

if (-not $NoPush) {
    Write-Host "To start the stack, run:" -ForegroundColor Yellow
    Write-Host "  docker compose up -d" -ForegroundColor Cyan
}
