FROM python:3.11-slim

# ── System dependencies ───────────────────────────────────────────────────────
# docker-ce-cli  : runs docker commands against the host daemon (socket mount)
# mender-artifact: wraps signed .mender artifact creation
# skopeo         : image inspection/copy used by gen_docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
        mender-artifact \
        skopeo && \
    # Add Docker's official apt repo and install only the CLI
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── gen_docker-compose (bundled from tools/) ──────────────────────────────────
COPY tools/gen_docker-compose /usr/bin/gen_docker-compose
RUN chmod +x /usr/bin/gen_docker-compose

# ── Python app ────────────────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8888

CMD ["python", "bundle-gui.py", "--host", "0.0.0.0", "--no-browser"]
