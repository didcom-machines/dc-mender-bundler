# dc-mender-bundler

Web GUI for packaging Docker Compose projects into Mender OTA artifacts. Single-file Python app (`bundle-gui.py`). All HTML/CSS/JS is embedded — no external JS dependencies.

## Run

```bash
pip install pyyaml
sudo apt install python3-tk   # for native file picker dialogs
python3 bundle-gui.py         # opens http://localhost:8888
```

Optional flags: `--port <n>`, `--no-browser`.

---

## What it does

1. Define a Docker Compose project visually (or import an existing `docker-compose.yml`)
2. Build or collect images for a target architecture
3. Bundle everything into a `.mender` artifact using `gen_docker-compose`

The output is a self-contained `.mender` file containing the compose manifest and all image tarballs, ready to deploy via the Mender server.

---

## Mender artifact structure

`gen_docker-compose` (Northern.tech official tool, must be at `/usr/bin/gen_docker-compose`) expects:

```
output-dir/
├── images/
│   ├── service-a.tar     ← one per service (docker save output)
│   └── service-b.tar
└── manifests/
    └── docker-compose.yml   ← image: references only, no build:
```

```bash
gen_docker-compose \
  --artifact-name  my-project-v1.0.0 \
  --device-type    my-device-type \
  --project-name   my-project \        # [a-zA-Z0-9_-] only
  --manifests-dir  output-dir/manifests \
  --images-dir     output-dir/images \
  --output-path    my-project-v1.0.0.mender
```

---

## bundle-gui.py — design

### UI layout

All sections are always visible (no step wizard). Import just pre-populates the same editor used when creating from scratch.

| Section | Purpose |
|---------|---------|
| Compose Project | Import bar + visual builder (left) + live YAML editor (right) |
| Dockerfiles | Tabbed editor per `build`-type service, appears automatically |
| Project Structure | Source directory tree + output directory tree (live preview) |
| Build Configuration | Architecture, artifact name, project name, device type, output dir |
| Build Output | Streaming log via SSE |

### Service types

| Type | How the image ends up in `images/` |
|------|------------------------------------|
| `image` | `docker images -q` check → use local if found; else `docker pull --platform <arch>` then `docker save` |
| `build` | `docker buildx build --platform <arch> --load` → `docker save` |
| `tar` | `shutil.copy2(tarPath, images_dir/name.tar)` — no Docker involved |

The `tar` type exists because cross-compiled images (e.g. `linux/arm64` built on an x86 machine) often don't exist in any registry. The tar path is not representable in docker-compose YAML, so `startBuild()` sends the full `services` array in the POST body alongside the compose path; the backend reads `tarPath` from there instead of re-parsing the YAML.

### Backend endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve embedded HTML |
| GET | `/images/local` | List local Docker images |
| GET | `/images/search?q=` | Search Docker Hub |
| POST | `/browse` | Native file/directory picker (tkinter) |
| POST | `/read-file` | Read a file from disk → content string |
| POST | `/write-file` | Write content string → file (creates dirs) |
| POST | `/parse-yaml` | Parse YAML string → services + networks list |
| POST | `/parse` | Parse compose file by path → services |
| POST | `/start` | Launch background build job → `{jobId}` |
| GET | `/stream/{jobId}` | SSE stream of build log lines + `done` event |

### YAML editor sync

- **Visual builder → YAML**: debounced 300 ms, client-side `jsYaml()` serializer (no network round-trip)
- **YAML → visual builder**: `↓ Apply` button calls `POST /parse-yaml` → rebuilds service cards
- **Import**: fills both YAML textarea and visual service cards simultaneously

### Dockerfile editors

Appear as a tabbed card whenever at least one service is type `build`. Each tab has Load (reads file from disk via `/read-file`) and Save (writes via `/write-file`) buttons. Tab key inserts 4-space indentation.

---

## GitHub

Repo: https://github.com/didcom-machines/dc-mender-bundler  
Org: `didcom-machines`  
Default branch: `main`
