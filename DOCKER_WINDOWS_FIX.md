# Docker Build Issues on Windows — Solutions & Workarounds

## Root Cause
Docker Compose on Windows with BuildKit fails to transfer the full build context when building services from a monorepo structure.

**Error:**
```
ERROR: failed to calculate checksum of ref: "/anomaly_engine": not found
```

**Why it happens:**
- Docker BuildKit context is only transferred as ~2 bytes instead of full project files
- This is a Docker Desktop/WSL2 issue with BuildKit on Windows  
- The legacy Docker builder works fine

## Immediate Fix (RECOMMENDED)

### Option A: Use Legacy Docker Builder
Set environment variable before building:

**PowerShell:**
```powershell
$env:DOCKER_BUILDKIT=1
$env:COMPOSE_DOCKER_CLI_BUILD=1
docker compose build anomaly_engine
```

**CMD:**
```cmd
set DOCKER_BUILDKIT=1
set COMPOSE_DOCKER_CLI_BUILD=1
docker compose build anomaly_engine
```

Or use the provided script:
```powershell
.\docker-build.ps1
.\docker-build.ps1 -Service anomaly_engine
```

### Option B: Use Direct Docker Build (Per Service)
```bash
docker build -f anomaly_engine/Dockerfile -t scaleguard-anomaly:latest .
```

Build all services:
```bash
for /D %s in (*_*) do docker build -f %s/Dockerfile -t scaleguard-%s:latest .
```

## Long-term Solutions

### 1. Update docker-compose.yml (v3.10+)
If Docker Desktop version supports it, add explicit build configuration:

```yaml
services:
  anomaly_engine:
    build:
      context: .
      dockerfile: anomaly_engine/Dockerfile
      x-bake:
        platforms:
          - linux/amd64
```

### 2. Docker Desktop Settings
Go to Settings → Docker Engine and ensure:
```json
{
  "features": {
    "buildkit": true
  }
}
```

Then restart Docker Desktop completely.

### 3. Migrate to Buildah/Podman (Advanced)
If Docker issues persist, consider using Buildah:
```bash
buildah build-using-dockerfile -f anomaly_engine/Dockerfile .
```

## Verification

After fix, verify with:
```bash
# Should work without errors
docker compose build anomaly_engine

# Or manually
docker build -f anomaly_engine/Dockerfile -t test:latest .
```

Check context is being transferred:
```bash
docker build --progress=plain -f anomaly_engine/Dockerfile .
```

Look for `load build context` showing reasonable size (should be 50+MB for full monorepo).

## Files Modified
- Added `.dockerignore` - Reduces context size and excludes unnecessary files
- Added `docker-build.ps1` - PowerShell helper with proper environment setup

## Additional Notes
- The Dockerfiles themselves are correct
- The build context and paths are correct
- This is purely a Docker Desktop + BuildKit issue on Windows
