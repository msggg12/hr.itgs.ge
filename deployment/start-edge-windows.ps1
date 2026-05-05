param(
  [string]$EnvFile = ".\\deployment\\edge.env.windows.example"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
  Write-Error "Env file not found: $EnvFile"
}

$resolvedEnvFile = Resolve-Path $EnvFile
$env:COMPOSE_ENV_FILES = $resolvedEnvFile

Write-Host "Using env file: $resolvedEnvFile"
docker compose --env-file $resolvedEnvFile -f docker-compose.edge.yml up --build -d
docker compose --env-file $resolvedEnvFile -f docker-compose.edge.yml ps
Write-Host "Health check: http://localhost:8010/monitoring/healthz"
