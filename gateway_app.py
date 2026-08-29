#!/usr/bin/env python3
"""
M3 Dynamic Aggregation Gateway & Control Center
Fully replaces New-API with zero external DB dependencies.
Built-in Input Hard-Trimming, Output Token Clamping & Load Balancing.
"""
import os
import json
import random
import aiohttp
from aiohttp import web

CONFIG_PATH = os.environ.get("GW_CONFIG_PATH", "/opt/stack-deploy/gateway/gateway_config.json")
DEFAULT_PORT = int(os.environ.get("GW_PORT", "8080"))

DEFAULT_DATA = {
    "security": {
        "admin_key": "sk-admin-root",
        "allowed_client_keys": ["sk-astrbot-client-key"]
    },
    "global_limits": {
        "force_max_input_chars": 40,
        "force_max_output_tokens": 40,
        "keep_last_n_messages": 1,
        "override_temperature": 0.2,
        "stream_response": True
    },
    "channels": [
        {
            "id": "ch-default-1",
            "name": "OpenAI / Gemini 聚合通道",
            "active": True,
            "base_url": "https://api.openai.com",
            "api_key": "sk-your-actual-api-key-here",
            "models": ["gpt-4o-mini", "gpt-3.5-turbo", "gemini-2.5-flash"],
            "model_mapping": {
                "openai/gemini-2.5-flash-lite": "gemini-2.5-flash"
            }
        }
    ]
}

def load_data():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2, ensure_ascii=False)
        return DEFAULT_DATA
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_DATA

def save_data(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

db = load_data()

HTML_UI = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>M3 Gateway Console</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0">
  <style>
    :root {
      --md-sys-color-primary: #00639b;
      --md-sys-color-on-primary: #ffffff;
      --md-sys-color-primary-container: #cce5ff;
      --md-sys-color-on-primary-container: #001d32;
      --md-sys-color-surface: #fdfcff;
      --md-sys-color-surface-container: #f0f4f8;
      --md-sys-color-surface-container-high: #e2e9ef;
      --md-sys-color-on-surface: #1a1c1e;
      --md-sys-color-outline: #72777e;
      --md-sys-color-outline-variant: #c2c7ce;
      --md-sys-color-error: #ba1a1a;
      --md-sys-color-error-container: #ffdad6;
      --md-sys-color-on-error: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: 'Roboto', sans-serif;
      background: var(--md-sys-color-surface);
      color: var(--md-sys-color-on-surface);
    }
    .top-app-bar {
      background: var(--md-sys-color-primary-container);
      color: var(--md-sys-color-on-primary-container);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      gap: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
    .container {
      max-width: 1100px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .card {
      background: #ffffff;
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 24px;
    }
    .card-title {
      font-size: 1.2rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
      color: var(--md-sys-color-primary);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .field {
      margin-bottom: 16px;
    }
    .field label {
      display: block;
      font-size: 0.85rem;
      color: var(--md-sys-color-outline);
      margin-bottom: 6px;
      font-weight: 500;
    }
    .field input, .field textarea, .field select {
      width: 100%;
      padding: 12px;
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 8px;
      font-size: 0.95rem;
      font-family: monospace;
      background: var(--md-sys-color-surface);
    }
    .channel-box {
      background: var(--md-sys-color-surface-container);
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      border-radius: 8px;
      border: none;
      background: var(--md-sys-color-primary);
      color: var(--md-sys-color-on-primary);
      font-weight: 500;
      cursor: pointer;
    }
    .btn-danger {
      background: var(--md-sys-color-error);
      color: var(--md-sys-color-on-error);
    }
    .action-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 16px;
    }
  </style>
</head>
<body>
  <div class="top-app-bar">
    <span class="material-symbols-outlined">tune</span>
    <span style="font-size: 1.25rem; font-weight: 700;">M3 全功能聚合模型网关管理控制台</span>
  </div>

  <div class="container">
    <!-- 全局输入输出流控参数 -->
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">data_thresholding</span> 全局 Token 与硬切片物理拦截
      </div>
      <div class="grid">
        <div class="field">
          <label>单次输入强制最大字符数 (0 为不限)</label>
          <input type="number" id="force_max_input_chars">
        </div>
        <div class="field">
          <label>单次输出物理锁定 Max Tokens</label>
          <input type="number" id="force_max_output_tokens">
        </div>
        <div class="field">
          <label>历史上下文强制保留轮数 (设为 1 杜绝历史叠加)</label>
          <input type="number" id="keep_last_n_messages">
        </div>
        <div class="field">
          <label>强制 Temperature 覆盖</label>
          <input type="number" step="0.1" id="override_temperature">
        </div>
      </div>
    </div>

    <!-- 安全认证 -->
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">shield</span> 安全与鉴权密钥配置
      </div>
      <div class="grid">
        <div class="field">
          <label>控制台管理密钥 (sk-admin-xxx)</label>
          <input type="text" id="admin_key">
        </div>
        <div class="field">
          <label>允许客户端调用的 API Keys (每行一个)</label>
          <textarea rows="3" id="allowed_client_keys"></textarea>
        </div>
      </div>
    </div>

    <!-- 上游模型聚合渠道管理 -->
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">account_tree</span> 上游模型聚合调度渠道 (负载均衡)
      </div>
      <div id="channelContainer"></div>
      <div class="action-bar">
        <button class="btn" onclick="addChannel()">
          <span class="material-symbols-outlined">add</span> 添加新上游渠道
        </button>
        <button class="btn" onclick="saveAll()">
          <span class="material-symbols-outlined">save</span> 立即热同步生效
        </button>
      </div>
    </div>
  </div>

  <script>
    let configState = {};

    async function loadConfig() {
      const res = await fetch('/_admin/api/config');
      configState = await res.json();

      document.getElementById('force_max_input_chars').value = configState.global_limits.force_max_input_chars;
      document.getElementById('force_max_output_tokens').value = configState.global_limits.force_max_output_tokens;
      document.getElementById('keep_last_n_messages').value = configState.global_limits.keep_last_n_messages;
      document.getElementById('override_temperature').value = configState.global_limits.override_temperature;

      document.getElementById('admin_key').value = configState.security.admin_key;
      document.getElementById('allowed_client_keys').value = configState.security.allowed_client_keys.join('\\n');

      renderChannels();
    }

    function renderChannels() {
      const box = document.getElementById('channelContainer');
      box.innerHTML = '';
      configState.channels.forEach((ch, idx) => {
        box.innerHTML += `
          <div class="channel-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px;">
              <strong>${ch.name || '聚合通道'}</strong>
              <button class="btn btn-danger" style="padding: 4px 8px;" onclick="removeChannel(${idx})">
                <span class="material-symbols-outlined" style="font-size:18px;">delete</span>
              </button>
            </div>
            <div class="grid">
              <div class="field">
                <label>通道名称</label>
                <input value="${ch.name}" onchange="configState.channels[${idx}].name = this.value">
              </div>
              <div class="field">
                <label>上游 Base URL</label>
                <input value="${ch.base_url}" onchange="configState.channels[${idx}].base_url = this.value">
              </div>
              <div class="field">
                <label>上游 API Key (Token)</label>
                <input type="password" value="${ch.api_key}" onchange="configState.channels[${idx}].api_key = this.value">
              </div>
              <div class="field">
                <label>支持的模型 (英文逗号分隔)</label>
                <input value="${ch.models.join(',')}" onchange="configState.channels[${idx}].models = this.value.split(',').map(s => s.trim())">
              </div>
            </div>
          </div>
        `;
      });
    }

    function addChannel() {
      configState.channels.push({
        id: "ch-" + Math.random().toString(36).substring(7),
        name: "新建上游渠道",
        active: true,
        base_url: "https://api.openai.com",
        api_key: "sk-xxx",
        models: ["gpt-4o-mini", "gemini-2.5-flash"],
        model_mapping: {}
      });
      renderChannels();
    }

    function removeChannel(idx) {
      configState.channels.splice(idx, 1);
      renderChannels();
    }

    async function saveAll() {
      configState.global_limits.force_max_input_chars = parseInt(document.getElementById('force_max_input_chars').value) || 0;
      configState.global_limits.force_max_output_tokens = parseInt(document.getElementById('force_max_output_tokens').value) || 40;
      configState.global_limits.keep_last_n_messages = parseInt(document.getElementById('keep_last_n_messages').value) || 1;
      configState.global_limits.override_temperature = parseFloat(document.getElementById('override_temperature').value) || 0.2;

      configState.security.admin_key = document.getElementById('admin_key').value;
      configState.security.allowed_client_keys = document.getElementById('allowed_client_keys').value.split('\\n').filter(s => s.trim().length > 0);

      await fetch('/_admin/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configState)
      });
      alert('网关配置已更新并实时生效！');
    }

    loadConfig();
  </script>
</body>
</html>
"""

async def admin_page(request):
    return web.Response(text=HTML_UI, content_type='text/html')

async def get_config_api(request):
    return web.json_response(db)

async def post_config_api(request):
    global db
    db = await request.json()
    save_data(db)
    return web.json_response({"status": "ok"})

async def models_handler(request):
    model_list = []
    for ch in db.get("channels", []):
        if ch.get("active", True):
            for m in ch.get("models", []):
                model_list.append({"id": m, "object": "model", "owned_by": "m3-gateway"})
    return web.json_response({"object": "list", "data": model_list})

async def chat_handler(request):
    # 1. 客户端 Token 认证
    auth_header = request.headers.get("Authorization", "")
    client_token = auth_header.replace("Bearer ", "").strip()
    allowed_keys = db.get("security", {}).get("allowed_client_keys", [])
    admin_key = db.get("security", {}).get("admin_key", "")
    
    if allowed_keys and (client_token not in allowed_keys and client_token != admin_key):
        return web.json_response({"error": {"message": "Invalid Client API Key", "type": "auth_error"}}, status=401)

    try:
        req_data = await request.json()
    except Exception:
        return web.json_response({"error": {"message": "Invalid JSON Body"}}, status=400)

    # 2. 获取目标模型并匹配上游渠道
    req_model = req_data.get("model", "")
    matched_channels = []
    for ch in db.get("channels", []):
        if ch.get("active", True):
            if req_model in ch.get("models", []) or req_model in ch.get("model_mapping", {}):
                matched_channels.append(ch)

    if not matched_channels:
        matched_channels = [ch for ch in db.get("channels", []) if ch.get("active", True)]
    
    if not matched_channels:
        return web.json_response({"error": {"message": f"No available upstream channel for model {req_model}"}}, status=503)

    target_ch = random.choice(matched_channels)
    final_model = target_ch.get("model_mapping", {}).get(req_model, req_model)
    req_data["model"] = final_model

    # 3. 核心物理拦截：输入截断 + 单轮历史裁剪 + 输出 Tokens 锁死
    limits = db.get("global_limits", {})
    max_in = limits.get("force_max_input_chars", 40)
    max_out = limits.get("force_max_output_tokens", 40)
    keep_n = limits.get("keep_last_n_messages", 1)

    if "messages" in req_data and isinstance(req_data["messages"], list):
        # 强制只留最后 N 轮
        if len(req_data["messages"]) > keep_n:
            req_data["messages"] = req_data["messages"][-keep_n:]

        # 强制将最新用户输入做字符级切片
        last_msg = req_data["messages"][-1]
        content = last_msg.get("content", "")
        if isinstance(content, str) and max_in > 0 and len(content) > max_in:
            last_msg["content"] = content[:max_in]

    # 输出 Token 强写
    req_data["max_tokens"] = max_out
    if "temperature" in limits:
        req_data["temperature"] = limits.get("override_temperature", 0.2)

    # 4. 向上游转发流式/非流式响应
    upstream_url = f"{target_ch['base_url'].rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {target_ch['api_key']}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(upstream_url, headers=headers, json=req_data) as resp:
                response = web.StreamResponse(status=resp.status, headers=resp.headers)
                response.headers["Access-Control-Allow-Origin"] = "*"
                await response.prepare(request)
                async for chunk in resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
        except Exception as e:
            return web.json_response({"error": {"message": f"Upstream proxy failed: {str(e)}"}}, status=502)

def create_app():
    app = web.Application()
    # 根路由与管理页面
    app.router.add_get('/', admin_page)
    app.router.add_get('/_admin', admin_page)
    app.router.add_get('/_admin/api/config', get_config_api)
    app.router.add_post('/_admin/api/config', post_config_api)

    # OpenAI 标准协议接口
    app.router.add_get('/v1/models', models_handler)
    app.router.add_post('/v1/chat/completions', chat_handler)
    return app

if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=DEFAULT_PORT)
