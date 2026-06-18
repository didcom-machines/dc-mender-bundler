import os
import queue
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from .compose import _parse_compose_data


def _run(cmd: list, q: queue.Queue, cwd: str = None) -> int:
    q.put(("info", "$ " + " ".join(cmd)))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
    for line in proc.stdout:
        q.put(("", line.rstrip()))
    proc.wait()
    return proc.returncode


def run_build_job(job: dict, params: dict):
    q: queue.Queue = job["queue"]

    def emit(msg, kind=""):
        q.put((kind, msg))

    tmp_dir = None
    try:
        architecture    = params["architecture"]
        artifact_name   = params["artifactName"]
        project_name    = params["projectName"]
        device_type     = params["deviceType"]
        compose_content = params.get("composeContent", "").strip()

        if not compose_content:
            raise RuntimeError("No compose content provided")
        if re.search(r"[^a-zA-Z0-9_-]", project_name):
            raise ValueError(f"Project name '{project_name}' must contain only a-z A-Z 0-9 _ -")

        tmp_dir       = tempfile.mkdtemp(prefix="mender-bundle-")
        output_dir    = Path(tmp_dir)
        images_dir    = output_dir / "images"
        manifests_dir = output_dir / "manifests"
        images_dir.mkdir()
        manifests_dir.mkdir()

        compose_path = manifests_dir / "docker-compose.yml"
        compose_path.write_text(compose_content, encoding="utf-8")
        emit(f"Compose manifest written → {compose_path}", "info")

        if params.get("services"):
            services = params["services"]
            emit(f"Using {len(services)} service(s) from editor", "info")
        else:
            services = _parse_compose_data(yaml.safe_load(compose_content), Path("."))
            emit(f"Found {len(services)} service(s)", "info")

        for svc in services:
            name     = svc.get("name") or "unknown"
            svc_type = svc.get("type", "image")
            emit(f"\n── {name} ({svc_type}) {'─'*40}", "info")

            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            tar  = images_dir / f"{safe}.tar"

            if svc_type == "tar":
                tar_src = svc.get("tarPath", "").strip()
                if not tar_src:
                    raise RuntimeError(f"No tar path set for service '{name}'")
                if not os.path.isfile(tar_src):
                    raise RuntimeError(f"Tar file not found: {tar_src}")
                emit(f"Copying {tar_src} → {tar}", "info")
                shutil.copy2(tar_src, tar)

            elif svc_type == "build":
                tag = svc.get("tag") or name + ":latest"
                cmd = ["docker", "buildx", "build", "--platform", architecture, "--load", "-t", tag]
                if svc.get("dockerfile"):
                    cmd += ["-f", svc["dockerfile"]]
                ctx = svc.get("context", ".")
                cmd.append(ctx)
                if _run(cmd, q, cwd=ctx) != 0:
                    raise RuntimeError(f"Build failed for '{name}'")
                emit(f"Exporting → {tar}", "info")
                if _run(["docker", "save", tag, "-o", str(tar)], q) != 0:
                    raise RuntimeError(f"Export failed for '{name}'")

            else:  # image — use local if present, otherwise pull
                tag = svc.get("tag") or svc.get("image") or name + ":latest"
                check = subprocess.run(
                    ["docker", "images", "-q", tag],
                    capture_output=True, text=True, timeout=10,
                )
                if check.stdout.strip():
                    emit(f"Image {tag} found locally — skipping pull", "info")
                else:
                    emit(f"Image not found locally — pulling {tag}", "info")
                    if _run(["docker", "pull", "--platform", architecture, tag], q) != 0:
                        raise RuntimeError(f"Pull failed for '{name}': {tag}")
                emit(f"Exporting → {tar}", "info")
                if _run(["docker", "save", tag, "-o", str(tar)], q) != 0:
                    raise RuntimeError(f"Export failed for '{name}'")

        artifact_path = str(output_dir / f"{artifact_name}.mender")
        emit("\n── Bundling Mender artifact ──────────────────────────────", "info")
        if _run([
            "gen_docker-compose",
            "--artifact-name", artifact_name,
            "--device-type",   device_type,
            "--project-name",  project_name,
            "--manifests-dir", str(manifests_dir),
            "--images-dir",    str(images_dir),
            "--output-path",   artifact_path,
        ], q) != 0:
            raise RuntimeError("gen_docker-compose failed")

        emit(f"\nArtifact ready: {artifact_path}", "ok")
        job["status"]   = "success"
        job["artifact"] = artifact_path

    except Exception as exc:
        emit(f"\n{exc}", "err")
        job["status"]   = "error"
        job["artifact"] = ""
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        q.put(None)
