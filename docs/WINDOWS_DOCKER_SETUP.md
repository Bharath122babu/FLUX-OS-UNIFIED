# Windows Docker setup

The local setup on 18 October 2026 installed WSL **3.0.3**, Docker Desktop **4.95.0** in per-user mode, and Docker Engine **29.8.2**. Both the production acceptance smoke and the paired evaluator smoke passed using real containers after the restart.

1. Open Docker Desktop and allow the engine to start.
2. Check `wsl --version`. This project uses WSL 2. A message about WSL 1 being unavailable does not change the configured default version 2.
3. Run the checks below from the repository root.
4. For the four-task, eight-run Gemma pilot, run `powershell -File scripts/run_gemma_pilot.ps1`. The launcher prepares missing runtime images and runs the Docker smoke before permitting paid calls. Its API-key prompt hides input and does not save a key file.

```powershell
# The explicit path works from a terminal opened before Docker was installed.
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
$env:PATH = $dockerBin + ';' + $env:PATH
docker version
docker pull python:3.12-alpine
docker pull node:22-alpine
python scripts/docker_acceptance_smoke.py
python scripts/evaluation_docker_smoke.py
```

`docker version` should show both client and server. A client without a reachable server means Docker Desktop's engine still needs attention. The “Welcome to WSL” window is an information screen and can be closed.

Docker Desktop's [official Windows installation guide](https://docs.docker.com/desktop/setup/install/windows-install/) covers supported Windows versions, per-user installation and first-run setup. Microsoft's [WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install) covers enabling WSL and the required restart. The downloaded installer used during this session matched SHA-256 `73431db38491f770543880366228a23c993f84d1e8e045f56d83b8a98940cf76` and had a valid Docker Inc. signature.
