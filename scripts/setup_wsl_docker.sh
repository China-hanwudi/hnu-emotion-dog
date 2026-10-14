#!/bin/sh
set -eu
gateway="$1"
export HTTP_PROXY="http://$gateway:17897"
export HTTPS_PROXY="$HTTP_PROXY"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTP_PROXY"
export DEBIAN_FRONTEND=noninteractive
# HTTPS repositories use the existing authenticated TLS download path.
sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=30 update --error-on=any
apt-get install -y ca-certificates curl python3 iptables
install -m 0755 -d /etc/apt/keyrings
curl --fail --retry 5 --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
install -d /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/emotion-dog-proxy.conf <<'EOF'
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:17897" "HTTPS_PROXY=http://127.0.0.1:17897" "NO_PROXY=localhost,127.0.0.1,::1"
EOF
systemctl daemon-reload
apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=30 update --error-on=any
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
docker --version
docker compose version
