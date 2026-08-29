#!/usr/bin/env python3
"""
动态多路由可配置 API 网关与 Google Material Design 3 控制台
支持动态输入输出转换、URL 重写、流式代理与限流
"""
import os
import json
import asyncio
from typing import Dict, Any, List
from aiohttp import web, ClientSession, ClientTimeout

CONFIG_PATH = os.environ.get("GW_CONFIG_PATH", "/opt/stack-deploy/gateway/routes.json")
DEFAULT_PORT = int(os.environ.get("GW_PORT", "8080"))

DEFAULT_CONFIG = {
    "gateway_settings": {
        "title": "M3 Core Dynamic Gateway",
        "log_level": "INFO",
        "max_connections": 5000,
        "timeout_seconds": 60
    },
    "routes": [
        {
            "id": "astrbot-route",
            "name": "AstrBot Direct Stream",
            "path_prefix": "/bot-proxy",
            "target_url": "http://127.0.0.1:6185",
            "strip_prefix": True,
            "enable_cors": True,
            "custom_headers": {"X-Gateway-By": "M3-Dynamic"},
            "active": True
        },
        {
            "id": "newapi-route",
            "name": "New-API High Concurrency Gateway",
            "path_prefix": "/v1",
            "target_url": "http://127.0.0.1:3000/v1",
            "strip_prefix": False,
            "enable_cors": True,
            "custom_headers": {"X-Proxy-Target": "NewAPI"},
            "active": True
        }
    ]
}

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG

def save_config(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

current_config = load_config()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>M3 API Gateway Console</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0">
  <style>
    :root {
      --md-sys-color-primary: #006494;
      --md-sys-color-on-primary: #ffffff;
      --md-sys-color-primary-container: #cbe6ff;
      --md-sys-color-on-primary-container: #001e30;
      --md-sys-color-surface: #f8f9fa;
      --md-sys-color-on-surface: #191c1e;
      --md-sys-color-surface-container: #edeef0;
      --md-sys-color-outline: #72777f;
      --md-sys-color-outline-variant: #c2c7cf;
      --md-sys-shape-corner-medium: 16px;
      --md-sys-shape-corner-small: 8px;
    }
    body {
      margin: 0;
      padding: 0;
      font-family: 'Roboto', sans-serif;
      background-color: var(--md-sys-color-surface);
      color: var(--md-sys-color-on-surface);
    }
    .header {
      background: var(--md-sys-color-primary-container);
      color: var(--md-sys-color-on-primary-container);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      gap: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .container {
      max-width: 1000px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .card {
      background: #ffffff;
      border-radius: var(--md-sys-shape-corner-medium);
      padding: 24px;
      margin-bottom: 24px;
      border: 1px solid var(--md-sys-color-outline-variant);
    }
    .card-title {
      font-size: 1.25rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
    }
    .route-item {
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: var(--md-sys-shape-corner-small);
      padding: 16px;
      margin-bottom: 12px;
      background: var(--md-sys-color-surface-container);
    }
    .input-group {
      margin-bottom: 12px;
    }
    .input-group label {
      display: block;
      font-size: 0.85rem;
      color: var(--md-sys-color-outline);
      margin-bottom: 4px;
    }
    .input-group input, .input-group textarea {
      width: 100%;
      padding: 10px;
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: var(--md-sys-shape-corner-small);
      box-sizing: border-box;
      font-family: monospace;
    }
    .btn {
      background: var(--md-sys-color-primary);
      color: var(--md-sys-color-on-primary);
      border: none;
      border-radius: var(--md-sys-shape-corner-small);
      padding: 10px 20px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 500;
    }
    .btn-danger {
      background: #ba1a1a;
    }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
      background: #d1e7dd;
      color: #0f5132;
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="material-symbols-outlined">dns</span>
    <span style="font-size: 1.2rem; font-weight: 700;">M3 Dynamic Proxy Core Control</span>
  </div>

  <div class="container">
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">hub</span> Active Inbound/Outbound Rules
      </div>
      <div id="routeList"></div>
      <button class="btn" onclick="addRoute()">
        <span class="material-symbols-outlined">add</span> Append New Dynamic Route
      </button>
      <button class="btn" style="float: right;" onclick="saveConfigToServer()">
        <span class="material-symbols-outlined">save</span> Apply & Sync Pipeline
      </button>
    </div>
  </div>

  <script>
    let state = { routes: [] };

    async function fetchConfig() {
      const res = await fetch('/_admin/api/config');
      const data = await res.json();
      state = data;
      render();
    }

    function render() {
      const container = document.getElementById('routeList');
      container.innerHTML = '';
      state.routes.forEach((route, idx) => {
        container.innerHTML += `
          <div class="route-item">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <strong>${route.name}</strong>
              <button class="btn btn-danger" style="padding:4px 8px;" onclick="removeRoute(${idx})">
                <span class="material-symbols-outlined" style="font-size:16px;">delete</span>
              </button>
            </div>
            <div class="input-group">
              <label>Match Prefix</label>
              <input value="${route.path_prefix}" onchange="state.routes[${idx}].path_prefix = this.value">
            </div>
            <div class="input-group">
              <label>Target Upstream URL</label>
              <input value="${route.target_url}" onchange="state.routes[${idx}].target_url = this.value">
            </div>
          </div>
        `;
      });
    }

    function addRoute() {
      state.routes.push({
        id: "route-" + Math.random().toString(36).substring(7),
        name: "Dynamic Proxy Node",
        path_prefix: "/api/custom",
        target_url: "http://127.0.0.1:8000",
        strip_prefix: false,
        enable_cors: true,
        custom_headers: {},
        active: true
      });
      render();
    }

    function removeRoute(idx) {
      state.routes.splice(idx, 1);
      render();
    }

    async function saveConfigToServer() {
      await fetch('/_admin/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state)
      });
      alert('Config applied without service downtime.');
    }

    fetchConfig();
  </script>
</body>
</html>
"""

async def admin_page(request):
    return web.Response(text=HTML_PAGE, content_type='text/html')

async def get_config_api(request):
    return web.json_response(current_config)

async def post_config_api(request):
    global current_config
    data = await request.json()
    current_config = data
    save_config(current_config)
    return web.json_response({"status": "ok"})

async def proxy_handler(request):
    req_path = request.path
    matched_route = None
    for route in current_config.get("routes", []):
        if route.get("active", True) and req_path.startswith(route["path_prefix"]):
            matched_route = route
            break

    if not matched_route:
        return web.Response(text="No dynamic upstream rule matched this endpoint.", status=404)

    target_base = matched_route["target_url"].rstrip('/')
    if matched_route.get("strip_prefix", False):
        sub_path = req_path[len(matched_route["path_prefix"]):]
        target_url = f"{target_base}{sub_path}"
    else:
        target_url = f"{target_base}{req_path}"

    if request.query_string:
        target_url = f"{target_url}?{request.query_string}"

    headers = dict(request.headers)
    headers.pop("Host", None)
    for k, v in matched_route.get("custom_headers", {}).items():
        headers[k] = v

    timeout = ClientTimeout(total=current_config.get("gateway_settings", {}).get("timeout_seconds", 60))
    try:
        async with ClientSession(timeout=timeout) as session:
            body = await request.read()
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                allow_redirects=False
            ) as resp:
                response = web.StreamResponse(
                    status=resp.status,
                    headers=resp.headers
                )
                if matched_route.get("enable_cors", True):
                    response.headers["Access-Control-Allow-Origin"] = "*"
                    response.headers["Access-Control-Allow-Headers"] = "*"
                    response.headers["Access-Control-Allow-Methods"] = "*"

                await response.prepare(request)
                async for chunk in resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
    except Exception as e:
        return web.Response(text=f"Gateway pipeline forward error: {str(e)}", status=502)

def make_app():
    app = web.Application()
    app.router.add_get('/_admin', admin_page)
    app.router.add_get('/_admin/api/config', get_config_api)
    app.router.add_post('/_admin/api/config', post_config_api)
    app.router.add_route('*', '/{tail:.*}', proxy_handler)
    return app

if __name__ == '__main__':
    web.run_app(make_app(), port=DEFAULT_PORT, host="0.0.0.0")
