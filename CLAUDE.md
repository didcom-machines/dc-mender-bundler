# dc-mender-bundler

Web GUI for packaging Docker Compose projects into Mender OTA artifacts. Single-file Python app (`bundle-gui.py`). No external JS dependencies — all HTML/CSS/JS is embedded in the Python file.

## Run

```bash
pip install pyyaml
sudo apt install python3-tk   # for native file picker
python3 bundle-gui.py         # opens http://localhost:8888
```

Optional flags: `--port <n>`, `--no-browser`.

---

## Why this exists

The target platform is an **automotive infotainment device** running embedded Linux with Docker. Images are cross-compiled for `linux/arm64` on a developer x86 machine. Because these images never exist in any registry, the standard Mender workflow (pull from registry on device) does not apply — images must be bundled into the `.mender` artifact alongside the compose manifest.

---

## Three-tier RPC architecture (the system this tool deploys for)

```
Browser / Client containers
        │  HTTP POST /rpc
        ▼
  ┌─────────────────────────────────┐
  │  Tier 2 — Gateway container     │  image: gateway-arm64:latest
  │  Flask HTTP → Unix socket proxy │  container: hardware-gateway
  │  Port 8765:80 (host:container)  │  network: hardware-gateway-net
  └─────────────────────────────────┘
        │  Unix socket
        ▼
  /tmp/rpc_server.sock  (Tier 1 — host RPC server, systemd service)
  Whitelist: /etc/rpc-server/whitelist_config.json
```

- **Tier 1** validates every command against a whitelist. Default: no commands allowed.
- **Tier 2** (gateway) bridges HTTP ↔ Unix socket. CORS controlled via `CORS_ORIGINS` env var.
- **Tier 3** (client containers) call `http://hardware-gateway/rpc` — no port needed because they're on `hardware-gateway-net`.

### RPC request format

```json
POST /rpc
{ "jsonrpc": "2.0", "method": "execute", "params": ["command", "arg1", "arg2"], "id": 1 }
```

`params[0]` is the command; `params[1:]` are its arguments. The `method` field is ignored by the host server.

### Network ownership rule

The **gateway project owns** `hardware-gateway-net`. Other compose projects join it as:
```yaml
networks:
  hardware-gateway-net:
    external: true
```

---

## Mender deployment

### Tool

`/usr/bin/gen_docker-compose` — Northern.tech official Update Module generator.

```bash
gen_docker-compose \
  --artifact-name  my-project-v1.0.0 \
  --device-type    automotive-infotainment-lite \
  --project-name   my-project \          # [a-zA-Z0-9_-] only
  --manifests-dir  ./manifests \
  --images-dir     ./images \
  --output-path    my-project-v1.0.0.mender
```

### Required directory structure

```
project/
├── images/
│   ├── service-a.tar     ← docker save output
│   └── service-b.tar
└── manifests/
    └── docker-compose.yml   ← image: only, no build:
```

### One-project constraint

The docker-compose Update Module uses `--clears-provides "*mender-docker-compose_*"`. **Deploying project B removes project A.** Each artifact is a full project replacement, not an additive update.

### Rollback

If `ArtifactCommit` fails (health check unhealthy), Mender runs `ArtifactRollback` automatically — tears down the new composition, restores the previous one.

### Port publishing on target

The target kernel requires these modules for Docker port publishing to work:
- `CONFIG_IP_NF_RAW=y`
- `CONFIG_IP_NF_FILTER=y`
- `CONFIG_NF_CONNTRACK=y`
- `CONFIG_NETFILTER_XT_MATCH_CONNTRACK=y`
- `CONFIG_NETFILTER_XT_MATCH_ADDRTYPE=y`

Without `iptable_raw`, any `ports:` mapping fails with `Table does not exist`.

---

## bundle-gui.py — architecture

### Backend endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve embedded HTML |
| GET | `/images/local` | List local Docker images |
| GET | `/images/search?q=` | Search Docker Hub |
| POST | `/browse` | Native file/directory picker (tkinter) |
| POST | `/read-file` | Read a file from disk → content string |
| POST | `/write-file` | Write content string → file on disk |
| POST | `/parse-yaml` | Parse YAML string → services + networks |
| POST | `/parse` | Parse compose file by path → services |
| POST | `/start` | Launch build job, returns `{jobId}` |
| GET | `/stream/{jobId}` | SSE stream of build log lines |

### Service types

| Type | How the image gets into `images/` |
|------|----------------------------------|
| `image` | `docker images -q` check → skip pull if local; else `docker pull` |
| `build` | `docker buildx build --platform <arch> --load` → `docker save` |
| `tar` | `shutil.copy2(tarPath, images_dir/name.tar)` — no Docker involved |

**Important**: tar path is not representable in docker-compose YAML. `startBuild()` sends the full `services` array in the POST body so the backend has `tarPath` per service. The backend uses `params["services"]` when present instead of re-parsing the compose file.

### YAML editor sync

- Visual builder → YAML: debounced 300 ms, JS-side `jsYaml()` serializer (no round-trip)
- YAML → visual builder: `↓ Apply` button calls `POST /parse-yaml` → rebuilds service cards
- Import: fills both YAML editor and visual cards simultaneously

### Dockerfile editors

Appear automatically when any service is type `build`. One tab per build service. Load/Save buttons read and write the actual file from disk via `/read-file` and `/write-file`.

---

## Key files in the broader project (outside this repo)

| Path | Description |
|------|-------------|
| `/home/manuelmonge/socket/gateway/gateway.py` | Flask gateway service |
| `/home/manuelmonge/socket/gateway/manifests/docker-compose.yml` | Gateway Mender deployment manifest |
| `/home/manuelmonge/socket/gateway/create-artifact.sh` | Gateway artifact build script |
| `/home/manuelmonge/socket/client_demo/manifests/docker-compose.yml` | Client demo deployment manifest |
| `/home/manuelmonge/socket/client_demo/create-artifact.sh` | Client demo artifact build script |
| `/home/manuelmonge/socket/MENDER_BUNDLE_GUIDE.md` | Full manual bundling guide |

---

## GitHub

Repo: https://github.com/didcom-machines/dc-mender-bundler  
Org: `didcom-machines`  
Default branch: `main`
