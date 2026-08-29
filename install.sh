#!/usr/bin/env bash
# ==============================================================================
# M3 自研聚合网关 + AstrBot 生产级极速部署控制器
# ==============================================================================

set -eo pipefail
export DEBIAN_FRONTEND=noninteractive

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BASE_DIR}/config.env"
RAW_BASE_URL="https://raw.githubusercontent.com/YiranrumengQAQ/Ai/main"

LOG_INFO="\033[34m[INFO]\033[0m"
LOG_SUCCESS="\033[32m[SUCCESS]\033[0m"
LOG_WARN="\033[33m[WARN]\033[0m"
LOG_ERROR="\033[31m[ERROR]\033[0m"

log() { echo -e "${LOG_INFO} $1"; }
ok()  { echo -e "${LOG_SUCCESS} $1"; }
warn(){ echo -e "${LOG_WARN} $1"; }
err() { echo -e "${LOG_ERROR} $1"; }

if [ "$EUID" -ne 0 ]; then
    err "必须使用 root 用户执行！"
    exit 1
fi

# 自动同步远端文件
if [ ! -f "$CONFIG_FILE" ]; then
    curl -fsSL "${RAW_BASE_URL}/config.env" -o "${BASE_DIR}/config.env" || true
fi
if [ ! -f "${BASE_DIR}/gateway_app.py" ]; then
    curl -fsSL "${RAW_BASE_URL}/gateway_app.py" -o "${BASE_DIR}/gateway_app.py" || true
fi

[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# 1. 彻底停止并销毁旧版 New-API 遗留容器与环境
cleanup_legacy() {
    log "清理废弃组件与旧版 New-API 容器..."
    docker stop new-api 2>/dev/null || true
    docker rm new-api 2>/dev/null || true
    rm -rf /etc/nginx/conf.d/newapi.conf /etc/nginx/conf.d/new_api.conf 2>/dev/null || true
}

# 2. 系统核心依赖安装
install_dependencies() {
    log "正在准备基础环境与 Python 运行时..."
    if command -v apt-get &>/dev/null; then
        apt-get update -y -q
        apt-get install -y -q curl wget sudo ufw iptables socat cron sqlite3 psmisc nginx procps net-tools iproute2 python3 python3-pip python3-aiohttp
    elif command -v yum &>/dev/null; then
        yum update -y -q
        yum install -y -q curl wget sudo firewalld iptables socat crontabs sqlite psmisc nginx procps net-tools iproute python3 python3-pip
    fi
    pip3 install --quiet --upgrade aiohttp --break-system-packages 2>/dev/null || true
    ok "核心依赖安装完成"
}

# 3. 网络与域名
setup_networking() {
    log "检测公网 IPv4..."
    IPV4_REGEX="^([0-9]{1,3}\.){3}[0-9]{1,3}$"
    VPS_IP=""
    for api in "https://api.ipify.org" "https://icanhazip.com" "https://ifconfig.me/ip"; do
        TEMP_IP=$(curl -s4m 4 "$api" | tr -d '\r\n ' || true)
        if [[ "$TEMP_IP" =~ $IPV4_REGEX ]]; then
            VPS_IP="$TEMP_IP"
            break
        fi
    done
    [ -z "$VPS_IP" ] && read -rp "请输入 VPS 公网 IP: " VPS_IP

    RAND_TAG=$(head /dev/urandom | tr -dc a-z0-9 | head -c 4)
    if [ "$AUTO_NIP_DOMAIN" = "true" ]; then
        BOT_DOMAIN="bot-${RAND_TAG}.${VPS_IP}.nip.io"
        GW_DOMAIN="gw-${RAND_TAG}.${VPS_IP}.nip.io"
    else
        BOT_DOMAIN="${CUSTOM_BOT_DOMAIN}"
        GW_DOMAIN="${CUSTOM_GW_DOMAIN}"
    fi

    if [ "$ENABLE_FIREWALL" = "true" ]; then
        for port in 80 443 "$PORT_GATEWAY_WEB"; do
            if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
                ufw allow "$port"/tcp >/dev/null 2>&1
            elif command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld; then
                firewall-cmd --permanent --add-port="$port"/tcp >/dev/null 2>&1
                firewall-cmd --reload >/dev/null 2>&1
            fi
        done
    fi
}

# 4. 部署 AstrBot
deploy_astrbot() {
    if [ "$INSTALL_DOCKER" = "true" ] && ! command -v docker &>/dev/null; then
        curl -fsSL https://get.docker.com | bash
        systemctl enable --now docker
    fi
    log "部署 AstrBot 容器..."
    mkdir -p "${DIR_ASTRBOT}/data"
    docker stop astrbot 2>/dev/null || true
    docker rm astrbot 2>/dev/null || true
    docker run -d \
      --name astrbot \
      --restart always \
      -e TZ=Asia/Shanghai \
      -p 127.0.0.1:${PORT_ASTRBOT_INTERNAL}:6185 \
      -v "${DIR_ASTRBOT}/data":/AstrBot/data \
      "$IMAGE_ASTRBOT"
    ok "AstrBot 部署完成"
}

# 5. 部署并启动 M3 自研聚合网关
deploy_gateway() {
    log "配置并启动 M3 聚合网关 Systemd 守护服务..."
    mkdir -p "$DIR_GATEWAY"
    cp "${BASE_DIR}/gateway_app.py" "${DIR_GATEWAY}/gateway_app.py" 2>/dev/null || true

    cat << SYSTEMD_GW > /etc/systemd/system/m3-gateway.service
[Unit]
Description=M3 Dynamic Aggregation Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${DIR_GATEWAY}
Environment=GW_CONFIG_PATH=${DIR_GATEWAY}/gateway_config.json
Environment=GW_PORT=${PORT_GATEWAY_WEB}
ExecStart=/usr/bin/python3 ${DIR_GATEWAY}/gateway_app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SYSTEMD_GW

    systemctl daemon-reload
    systemctl enable --now m3-gateway
    systemctl restart m3-gateway
    ok "M3 聚合网关服务运行中 (监听端口: ${PORT_GATEWAY_WEB})"
}

# 6. 配置 SSL 与 Nginx
setup_nginx() {
    log "配置 Nginx 虚拟主机与 SSL..."
    mkdir -p "$DIR_CERTS" /etc/nginx/conf.d
    rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf

    if [ "$ENABLE_SSL" = "true" ]; then
        systemctl stop nginx 2>/dev/null || true
        fuser -k 80/tcp 2>/dev/null || true
        if [ ! -f "$HOME/.acme.sh/acme.sh" ]; then
            curl https://get.acme.sh | sh -s email="ssl_${VPS_IP//./_}@gmail.com" >/dev/null 2>&1
        fi
        export PATH="$HOME/.acme.sh:$PATH"
        ~/.acme.sh/acme.sh --set-default-ca --server letsencrypt >/dev/null 2>&1

        issue_cert() {
            local domain=$1
            local name=$2
            ~/.acme.sh/acme.sh --issue -d "$domain" --standalone --server letsencrypt --force >/dev/null 2>&1 || true
            ~/.acme.sh/acme.sh --install-cert -d "$domain" --ecc \
                --key-file "$DIR_CERTS/${name}.key" \
                --fullchain-file "$DIR_CERTS/${name}.crt" >/dev/null 2>&1 || true
        }
        issue_cert "$BOT_DOMAIN" "bot"
        issue_cert "$GW_DOMAIN" "gw"
    fi

    make_block() {
        local domain=$1
        local port=$2
        local name=$3
        if [ "$ENABLE_SSL" = "true" ] && [ -f "$DIR_CERTS/${name}.crt" ]; then
            cat << BLOCK
server {
    listen 80;
    server_name $domain;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    http2 on;
    server_name $domain;
    ssl_certificate $DIR_CERTS/${name}.crt;
    ssl_certificate_key $DIR_CERTS/${name}.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:$port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
    }
}
BLOCK
        else
            cat << BLOCK
server {
    listen 80;
    server_name $domain;
    location / {
        proxy_pass http://127.0.0.1:$port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
    }
}
BLOCK
        fi
    }

    make_block "$BOT_DOMAIN" "$PORT_ASTRBOT_INTERNAL" "bot" > /etc/nginx/conf.d/astrbot.conf
    make_block "$GW_DOMAIN" "$PORT_GATEWAY_WEB" "gw" > /etc/nginx/conf.d/gateway.conf

    nginx -t
    systemctl enable --now nginx
    systemctl restart nginx
    ok "Nginx 转发与 SSL 就绪"
}

cleanup_legacy
install_dependencies
setup_networking
deploy_astrbot
deploy_gateway
setup_nginx

clear
PROTO="http"
[ "$ENABLE_SSL" = "true" ] && PROTO="https"

echo "================================================================"
echo "          M3 自研聚合网关与 AstrBot 集群已就绪                 "
echo "================================================================"
echo ">> [1] M3 全功能聚合网关控制台 (已替代 New-API)"
echo "   - 面板地址  : ${PROTO}://${GW_DOMAIN}"
echo "   - 直连面板  : http://${VPS_IP}:${PORT_GATEWAY_WEB}"
echo "   - 管理密钥  : sk-admin-root"
echo "   - 提供给 AstrBot 的 Base URL : ${PROTO}://${GW_DOMAIN}/v1"
echo "   - 提供给 AstrBot 的 API Key  : sk-astrbot-client-key"
echo "----------------------------------------------------------------"
echo ">> [2] AstrBot 核心控制台"
echo "   - 接入地址  : ${PROTO}://${BOT_DOMAIN}"
echo "   - 初始账密  : 执行 [docker logs astrbot] 查看"
echo "================================================================"
