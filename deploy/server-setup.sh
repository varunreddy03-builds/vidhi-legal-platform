#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu server (22.04 or 24.04, ARM or ordinary PC chip) for VIDHI. Run it ONCE, as root, after the machine exists:
#
#   sudo bash server-setup.sh <deploy-user> <public-key-file> [deploy-path]
#   sudo bash server-setup.sh deploy ./deploy_key.pub /srv/vidhi-staging
#
# What it does (docs/hosting-runbook.md sections 3 and 6.2): makes a normal deploy user that can log in with your deploy key, installs Docker from Docker's own package source, turns
# off password login and root login for SSH, opens only ports 22, 80 and 443, switches on automatic security updates, and prepares the deploy folder with the backup passphrase
# and backup folder the way the runbook asks. It does NOT start VIDHI (the Deploy workflow does) and it never prints the backup passphrase.
#
# STATUS: written 2026-11-05 and NOT YET RUN on any server. Read it before you run it, keep your first SSH session open while you test a second login, and fix anything it reports.
set -euo pipefail

DEPLOY_USER="${1:?usage: server-setup.sh <deploy-user> <public-key-file> [deploy-path]}"
PUBKEY_FILE="${2:?usage: server-setup.sh <deploy-user> <public-key-file> [deploy-path]}"
DEPLOY_PATH="${3:-/srv/vidhi-staging}"

[ "$(id -u)" -eq 0 ] || { echo "run this as root (sudo)" >&2; exit 1; }
[ -s "$PUBKEY_FILE" ] || { echo "the public key file is missing or empty: $PUBKEY_FILE" >&2; exit 1; }
grep -qE '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-)' "$PUBKEY_FILE" || { echo "that does not look like a public key (it must start with ssh-ed25519 or similar). Never use the private key here." >&2; exit 1; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || { echo "this script is written for Ubuntu; this is ${ID:-unknown}" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
echo "[1/7] packages"
apt-get update -y
apt-get install -y ca-certificates curl gnupg ufw unattended-upgrades openssl rsync

echo "[2/7] Docker Engine and the Compose plugin (Docker's own package source)"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "[3/7] the deploy user (${DEPLOY_USER}), key login only"
id "$DEPLOY_USER" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
touch "/home/${DEPLOY_USER}/.ssh/authorized_keys"
grep -qxFf "$PUBKEY_FILE" "/home/${DEPLOY_USER}/.ssh/authorized_keys" || cat "$PUBKEY_FILE" >> "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"

echo "[4/7] SSH: no passwords, no root login (only once the deploy key is in place)"
if [ -s "/home/${DEPLOY_USER}/.ssh/authorized_keys" ]; then
  cat > /etc/ssh/sshd_config.d/99-vidhi.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
  sshd -t
  systemctl reload ssh 2>/dev/null || systemctl reload sshd
else
  echo "no deploy key was installed, so SSH was left as it was" >&2
fi

echo "[5/7] firewall: only 22, 80 and 443"
if grep -qi oracle /sys/class/dmi/id/chassis_asset_tag /sys/class/dmi/id/sys_vendor 2>/dev/null; then
  # Oracle's Ubuntu images ship their own iptables rules that refuse new connections; ufw would fight them. Also open 80 and 443 in the Oracle console (the subnet's security list).
  apt-get install -y iptables-persistent netfilter-persistent
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
  done
  netfilter-persistent save
else
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

echo "[6/7] automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "[7/7] the deploy folder ${DEPLOY_PATH}"
mkdir -p "${DEPLOY_PATH}/secrets" "${DEPLOY_PATH}/backups"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_PATH"
if [ ! -s "${DEPLOY_PATH}/secrets/backup_passphrase" ]; then
  openssl rand -base64 32 > "${DEPLOY_PATH}/secrets/backup_passphrase"
  echo "a backup passphrase was created (it is not shown here)"
fi
# the backup container and the API run as user 10001: it must read the passphrase and write the backups and the erasure list
chown 10001:10001 "${DEPLOY_PATH}/secrets/backup_passphrase" "${DEPLOY_PATH}/backups"
chmod 400 "${DEPLOY_PATH}/secrets/backup_passphrase"
chmod 700 "${DEPLOY_PATH}/backups"

echo
echo "Done. Do these now:"
echo "  1. Open a SECOND terminal and log in as ${DEPLOY_USER} with your deploy key. Only close the first one when that works."
echo "  2. Copy the backup passphrase OFF this machine into your password manager:   sudo cat ${DEPLOY_PATH}/secrets/backup_passphrase"
echo "     Without it every backup is unreadable. Use a different passphrase for production."
echo "  3. Make sure ports 80 and 443 are also open in your cloud provider's own firewall or security list."
echo "  4. Point your domain's A record at this machine, then run the Deploy workflow (docs/hosting-runbook.md section 6.3)."
