from pathlib import Path

import yaml


def parse_compose_file(path: str) -> list:
    with open(path) as f:
        return _parse_compose_data(yaml.safe_load(f), Path(path).parent)


def parse_compose_string(content: str) -> dict:
    data = yaml.safe_load(content)
    services, networks = [], []

    for name, svc in (data.get("services") or {}).items():
        if not svc:
            continue
        build, image = svc.get("build"), svc.get("image")
        entry = {"name": name}
        if build:
            context = build if isinstance(build, str) else build.get("context", ".")
            dockerfile = build.get("dockerfile") if isinstance(build, dict) else ""
            entry.update({
                "type": "build", "context": context, "dockerfile": dockerfile or "",
                "tag": image or f"{name}:latest", "image": "",
            })
        elif image:
            entry.update({"type": "image", "image": image, "context": "", "dockerfile": "", "tag": ""})
        else:
            continue

        entry["containerName"] = svc.get("container_name", "")
        entry["restart"] = svc.get("restart", "unless-stopped")

        env = svc.get("environment", [])
        if isinstance(env, list):
            entry["envVars"] = [
                {"key": e.split("=", 1)[0], "value": e.split("=", 1)[1] if "=" in e else ""}
                for e in env
            ]
        elif isinstance(env, dict):
            entry["envVars"] = [{"key": k, "value": str(v)} for k, v in env.items()]
        else:
            entry["envVars"] = []

        vols = svc.get("volumes", [])
        entry["volumes"] = []
        for v in vols if isinstance(vols, list) else []:
            if isinstance(v, str):
                p = v.split(":", 1)
                entry["volumes"].append({"host": p[0], "container": p[1] if len(p) > 1 else p[0]})
            elif isinstance(v, dict):
                entry["volumes"].append({"host": v.get("source", ""), "container": v.get("target", "")})

        nets = svc.get("networks", [])
        entry["networks"] = list(nets.keys()) if isinstance(nets, dict) else (nets if isinstance(nets, list) else [])
        services.append(entry)

    for net_name, net_def in (data.get("networks") or {}).items():
        nd = net_def or {}
        networks.append({
            "name": net_name,
            "driver": nd.get("driver", "bridge"),
            "external": bool(nd.get("external", False)),
        })

    return {"services": services, "networks": networks}


def _parse_compose_data(data, compose_dir: Path) -> list:
    services = []
    for name, svc in (data.get("services") or {}).items():
        if not svc:
            continue
        build, image = svc.get("build"), svc.get("image")
        if build:
            context = build if isinstance(build, str) else build.get("context", ".")
            context = str((compose_dir / context).resolve())
            dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
            services.append({
                "name": name, "type": "build",
                "source": f"Dockerfile @ {context}",
                "tag": image or f"{name}:latest",
                "context": context, "dockerfile": dockerfile,
            })
        elif image:
            services.append({"name": name, "type": "image", "source": image, "tag": image})
    return services


def generate_compose_yaml(services: list, networks: list) -> str:
    doc: dict = {"services": {}}
    for svc in services:
        name = svc["name"]
        entry: dict = {}
        if svc["type"] == "build":
            build_def: dict = {"context": svc["context"]}
            if svc.get("dockerfile"):
                build_def["dockerfile"] = svc["dockerfile"]
            entry["build"] = build_def
            if svc.get("tag"):
                entry["image"] = svc["tag"]
        else:
            entry["image"] = svc["image"]
        if svc.get("containerName"):
            entry["container_name"] = svc["containerName"]
        if svc.get("restart"):
            entry["restart"] = svc["restart"]
        envs = [f"{e['key']}={e['value']}" for e in svc.get("envVars", []) if e.get("key")]
        if envs:
            entry["environment"] = envs
        vols = [f"{v['host']}:{v['container']}" for v in svc.get("volumes", []) if v.get("host")]
        if vols:
            entry["volumes"] = vols
        if svc.get("networks"):
            entry["networks"] = svc["networks"]
        doc["services"][name] = entry
    if networks:
        doc["networks"] = {}
        for net in networks:
            net_name = net["name"]
            if net.get("external"):
                doc["networks"][net_name] = {"external": True}
            else:
                doc["networks"][net_name] = {"name": net_name, "driver": net.get("driver", "bridge")}
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
