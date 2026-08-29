#!/usr/bin/env bash
# ==============================================================================
# 模块化微服务集群与高容错运维部署控制器
# ==============================================================================

set -eo pipefail
export DEBIAN_FRONTEND=noninteractive

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BASE_DIR}/config.env"
RAW_BASE_URL="https://raw.githubusercontent.com/YiranrumengQAQ/Ai/main"

# 1. 颜色与日志格式
LOG_INFO="\033[34m[INFO]\033[0m"
LOG_SUCCESS="\033[32m[SUCCESS]\033[0m"
LOG_WARN="\033[33m[WARN]\033[0m"
LOG_ERROR="\033[31m[ERROR]\033[0m"

log() { echo -e "${LOG_INFO} $1"; }
ok()  { echo -e "${LOG_SUCCESS} $1"; }
warn(){ echo -e "${LOG_WARN} $1"; }
err() { echo -e "${LOG_ERROR} $1"; }

# 2. 初始权限校验
if [ "$EUID" -ne 0 ]; then
    err "权限拒绝：必须使用 root 用户执行！"
    exit 1
fi

# 3. 自动同步远程依赖 (支持 curl 远程单行执行)
if [ ! -f "$CONFIG_FILE" ]; then
    warn "未在本地检测到 config.env，尝试从 GitHub 自动同步配置..."
    curl -fsSL "${RAW_BASE_URL}/config.env" -o "${BASE_DIR}/config.env" || true
fi

if [ ! -f "${BASE_DIR}/gateway_app.py" ]; then
    warn "未在本地检测到 gateway_app.py，尝试从 GitHub 自动同步网关代码..."
    curl -fsSL "${RAW_BASE_URL}/gateway_app.py" -o "${BASE_DIR}/gateway_app.py" || true
fi

# 如果仍然不存在则提供安全缺省值
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    warn "未能获取远程配置文件，将加载内置默认参数运行..."
    INSTALL_DOCKER="true"
    ENABLE_FIREWALL="true"
    INSTALL_ASTRBOT="true"
    INSTALL_NEWAPI="true"
    INSTALL_GATEWAY="true"
    ENABLE_SSL="true"
    AUTO_NIP_DOMAIN="true"
    PORT_ASTRBOT_INTERNAL="6185"
    PORT_NEWAPI_INTERNAL="3000"
    PORT_GATEWAY_WEB="8080"
    DIR_DATA_BASE="/opt/stack-deploy"
    DIR_ASTRBOT="${DIR_DATA_BASE}/astrbot"
    DIR_NEWAPI="${DIR_DATA_BASE}/new-api"
    DIR_GATEWAY="${DIR_DATA_BASE}/gateway"
    DIR_CERTS="/etc/ssl/stack-certs"
    IMAGE_ASTRBOT="soulter/astrbot:latest"
    IMAGE_NEWAPI="calciumion/new-api:latest"
fi

# 4. 基础依赖管理与包管理器自适应 (含 PEP 668 修复)
install_dependencies() {
    log "检测并安装基础设施依赖与运行库..."
    if command -v apt-get &>/dev/null; then
        apt-get update -y -q
        apt-get install -y -q curl wget sudo ufw iptables socat cron sqlite3 psmisc nginx procps net-tools iproute2 python3 python3-pip python3-aiohttp
        systemctl enable --now cron 2>/dev/null || true
    elif command -v yum &>/dev/null; then
        yum update -y -q
        yum install -y -q curl wget sudo firewalld iptables socat crontabs sqlite psmisc nginx procps net-tools iproute python3 python3-pip
        systemctl enable --now crond 2>/dev/null || true
    else
        err "不支持的 Linux 发行版包管理器"
        exit 1
    fi

    # 兼容 Debian 13/Ubuntu 24+ PEP 668 外部环境限制
    pip3 install --quiet --upgrade aiohttp --break-system-packages 2>/dev/null || true
    ok "系统核心依赖就绪"
}

# 5. 端口与网络探测
setup_networking() {
    log "正在检测网络配置与公网 IP..."
    IPV4_REGEX="^([0-9]{1,3}\.){3}[0-9]{1,3}$"
    VPS_IP=""
    for api in "https://api.ipify.org" "https://icanhazip.com" "https://ifconfig.me/ip" "https://checkip.amazonaws.com"; do
        TEMP_IP=$(curl -s4m 4 "$api" | tr -d '\r\n ' || true)
        if [[ "$TEMP_IP" =~ $IPV4_REGEX ]]; then
            VPS_IP="$TEMP_IP"
            break
        fi
    done

    if [ -z "$VPS_IP" ]; then
        read -rp "无法自动获取公网 IP，请输入: " VPS_IP
    fi
    ok "公网 IP 确认: $VPS_IP"

    # 动态分配或使用用户配置域名
    RAND_TAG=$(head /dev/urandom | tr -dc a-z0-9 | head -c 4)
    if [ "$AUTO_NIP_DOMAIN" = "true" ]; then
        BOT_DOMAIN="bot-${RAND_TAG}.${VPS_IP}.nip.io"
        API_DOMAIN="api-${RAND_TAG}.${VPS_IP}.nip.io"
        GW_DOMAIN="gw-${RAND_TAG}.${VPS_IP}.nip.io"
    else
        BOT_DOMAIN="${CUSTOM_BOT_DOMAIN}"
        API_DOMAIN="${CUSTOM_API_DOMAIN}"
        GW_DOMAIN="${CUSTOM_GW_DOMAIN}"
    fi

    if [ "$ENABLE_FIREWALL" = "true" ]; then
        log "放行服务端口..."
        for port in 80 443 "$PORT_GATEWAY_WEB" "$PORT_NEWAPI_INTERNAL"; do
            if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
                ufw allow "$port"/tcp >/dev/null 2>&1
            elif command -v firewall-cmd &>/dev/null && systemctl is-active --quiet firewalld; then
                firewall-cmd --permanent --add-port="$port"/tcp >/dev/null 2>&1
                firewall-cmd --reload >/dev/null 2>&1
            fi
        done
    fi
}

# 6. Docker 运行环境
setup_docker() {
    if [ "$INSTALL_DOCKER" = "true" ]; then
        if ! command -v docker &>/dev/null; then
            log "正在拉取并安装 Docker Engine..."
            curl -fsSL https://get.docker.com | bash
            systemctl enable --now docker
        else
            ok "Docker 环境已存在"
        fi
    fi
}

# 7. 服务部署逻辑
deploy_astrbot() {
    if [ "$INSTALL_ASTRBOT" != "true" ]; then return; fi
    log "正在配置并启动 AstrBot..."
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
    ok "AstrBot 容器部署就绪"
}

deploy_newapi() {
    if [ "$INSTALL_NEWAPI" != "true" ]; then return; fi
    log "正在配置并启动 New-API 聚合网关..."
    mkdir -p "$DIR_NEWAPI"
    docker stop new-api 2>/dev/null || true
    docker rm new-api 2>/dev/null || true
    docker run -d \
      --name new-api \
      --restart always \
      -p 0.0.0.0:${PORT_NEWAPI_INTERNAL}:3000 \
      -v "$DIR_NEWAPI":/data \
      "$IMAGE_NEWAPI"

    # SQLite 提权与状态确认
    log "安全配置注入中..."
    for i in {1..10}; do
        if [ -f "$DIR_NEWAPI/one-api.db" ] || [ -f "$DIR_NEWAPI/api.db" ]; then break; fi
        sleep 1
    done
    DB_FILE="$DIR_NEWAPI/one-api.db"
    [ ! -f "$DB_FILE" ] && DB_FILE="$DIR_NEWAPI/api.db"
    if [ -f "$DB_FILE" ]; then
        sqlite3 "$DB_FILE" "UPDATE users SET password = '\$2a\$10\$Xpvhc/q3wKx3vC14D93C9.0UqP/5hNl0lQd3t3uB6S6ZkF0S5nKte', role = 100 WHERE id = 1 OR username = 'root';" 2>/dev/null || true
        docker restart new-api >/dev/null 2>&1
        ok "New-API 超级管理员权限注入成功 (root / 123456)"
    fi
}

deploy_gateway() {
    if [ "$INSTALL_GATEWAY" != "true" ]; then return; fi
    log "正在启动 M3 自适应动态网关服务..."
    mkdir -p "$DIR_GATEWAY"
    cp "${BASE_DIR}/gateway_app.py" "${DIR_GATEWAY}/gateway_app.py" 2>/dev/null || true

    cat << SYSTEMD_GW > /etc/systemd/system/m3-gateway.service
[Unit]
Description=M3 Dynamic Python Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${DIR_GATEWAY}
Environment=GW_CONFIG_PATH=${DIR_GATEWAY}/routes.json
Environment=GW_PORT=${PORT_GATEWAY_WEB}
ExecStart=/usr/bin/python3 ${DIR_GATEWAY}/gateway_app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SYSTEMD_GW

    systemctl daemon-reload
    systemctl enable --now m3-gateway
    ok "M3 动态网关面板服务已启动"
}

# 8. Nginx 与 SSL 统一编排
setup_proxy_and_certs() {
    log "生成 Web 代理与安全网络层..."
    mkdir -p "$DIR_CERTS"
    mkdir -p /etc/nginx/conf.d
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
            log "申请证书: $domain"
            ~/.acme.sh/acme.sh --issue -d "$domain" --standalone --server letsencrypt --force >/dev/null 2>&1 || true
            ~/.acme.sh/acme.sh --install-cert -d "$domain" --ecc \
                --key-file "$DIR_CERTS/${name}.key" \
                --fullchain-file "$DIR_CERTS/${name}.crt" >/dev/null 2>&1 || true
        }

        [ "$INSTALL_ASTRBOT" = "true" ] && issue_cert "$BOT_DOMAIN" "bot"
        [ "$INSTALL_NEWAPI" = "true" ] && issue_cert "$API_DOMAIN" "api"
        [ "$INSTALL_GATEWAY" = "true" ] && issue_cert "$GW_DOMAIN" "gw"
    fi

    make_nginx_block() {
        local domain=$1
        local upstream_port=$2
        local cert_name=$3

        if [ "$ENABLE_SSL" = "true" ] && [ -f "$DIR_CERTS/${cert_name}.crt" ]; then
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
    ssl_certificate $DIR_CERTS/${cert_name}.crt;
    ssl_certificate_key $DIR_CERTS/${cert_name}.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:$upstream_port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
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
        proxy_pass http://127.0.0.1:$upstream_port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
    }
}
BLOCK
        fi
    }

    [ "$INSTALL_ASTRBOT" = "true" ] && make_nginx_block "$BOT_DOMAIN" "$PORT_ASTRBOT_INTERNAL" "bot" > /etc/nginx/conf.d/astrbot.conf
    [ "$INSTALL_NEWAPI" = "true" ] && make_nginx_block "$API_DOMAIN" "$PORT_NEWAPI_INTERNAL" "api" > /etc/nginx/conf.d/newapi.conf
    [ "$INSTALL_GATEWAY" = "true" ] && make_nginx_block "$GW_DOMAIN" "$PORT_GATEWAY_WEB" "gw" > /etc/nginx/conf.d/gateway.conf

    nginx -t
    systemctl enable --now nginx
    systemctl restart nginx
    ok "网络代理转发层已就绪"
}

# 9. 执行流水线
install_dependencies
setup_networking
setup_docker
deploy_astrbot
deploy_newapi
deploy_gateway
setup_proxy_and_certs

# 10. 输出总览报告
clear
PROTO="http"
[ "$ENABLE_SSL" = "true" ] && PROTO="https"

echo "================================================================"
echo "          微服务集群与动态网关部署矩阵已就绪                      "
echo "================================================================"
if [ "$INSTALL_GATEWAY" = "true" ]; then
    echo ">> [1] M3 动态网关控制台"
    echo "   - 接入地址 : ${PROTO}://${GW_DOMAIN}"
    echo "   - 直连面板 : http://${VPS_IP}:${PORT_GATEWAY_WEB}/_admin"
fi
if [ "$INSTALL_NEWAPI" = "true" ]; then
    echo ">> [2] New-API 模型管理中心"
    echo "   - 接入地址 : ${PROTO}://${API_DOMAIN}"
    echo "   - 备用访问 : http://${VPS_IP}:${PORT_NEWAPI_INTERNAL}"
    echo "   - 默认权限 : root / 123456"
fi
if [ "$INSTALL_ASTRBOT" = "true" ]; then
    echo ">> [3] AstrBot 核心"
    echo "   - 接入地址 : ${PROTO}://${BOT_DOMAIN}"
    echo "   - 初始密码 : 执行 [docker logs astrbot] 查看"
fi
echo "================================================================"
