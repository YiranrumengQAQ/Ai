#!/usr/bin/env python3
"""
M3 Ultimate Shield Gateway & Model Aggregation Hub
- Robust Multi-Version Config Migration & Persistence
- Deep Prompt Flattening (Stripping Tools, System, Schema, and Multi-turn Bloat)
- Arbitrary Hard Clamping for Input Characters and Output Tokens
- Zero-Downtime Hot Reload & Latency Ping Testing
"""
import os
import time
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
    "shield_limits": {
        "enable_super_shield": True,
        "custom_input_clamp_chars": 40,
        "custom_output_max_tokens": 40,
        "strip_system_prompts": True,
        "strip_tool_definitions": True,
        "strip_history_context": True,
        "override_temperature": 0.2
    },
    "channels": [
        {
            "id": "ch-default-1",
            "name": "OpenAI Labs Gemini",
            "active": True,
            "base_url": "https://www.openai-labs.com",
            "api_key": "",
            "models": ["gemini-2.5-flash-lite", "gpt-4o-mini"],
            "model_mapping": {}
        }
    ]
}

def load_data():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            # 兼容并自动迁移旧版本字段
            merged = DEFAULT_DATA.copy()
            merged["security"] = {**DEFAULT_DATA["security"], **raw.get("security", {})}
            
            old_limits = raw.get("global_limits", {})
            new_limits = raw.get("shield_limits", {})
            merged["shield_limits"] = {
                **DEFAULT_DATA["shield_limits"],
                **old_limits,
                **new_limits
            }
            if "force_max_output_tokens" in merged["shield_limits"] and "custom_output_max_tokens" not in new_limits:
                merged["shield_limits"]["custom_output_max_tokens"] = merged["shield_limits"].pop("force_max_output_tokens")
            if "max_total_input_chars" in merged["shield_limits"] and "custom_input_clamp_chars" not in new_limits:
                merged["shield_limits"]["custom_input_clamp_chars"] = merged["shield_limits"].pop("max_total_input_chars")

            channels = raw.get("channels", [])
            merged["channels"] = channels if channels else DEFAULT_DATA["channels"]
            return merged
    except Exception as e:
        print(f"[WARN] 加载配置失败，恢复默认: {e}")
        return DEFAULT_DATA

def save_data(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

db = load_data()

def sanitize_text(content):
    """递归提取任何复合数据类型中的纯文本"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "content" in item:
                    parts.append(sanitize_text(item["content"]))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    elif isinstance(content, dict):
        return content.get("text", "") or content.get("content", "")
    return str(content)

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
      --md-sys-color-primary-container: #cce5ff;
      --md-sys-color-on-primary-container: #001d32;
      --md-sys-color-surface: #fdfcff;
      --md-sys-color-surface-container: #f0f4f8;
      --md-sys-color-surface-container-high: #e2e9ef;
      --md-sys-color-on-surface: #1a1c1e;
      --md-sys-color-outline: #72777e;
      --md-sys-color-outline-variant: #c2c7ce;
      --md-sys-color-error: #ba1a1a;
      --md-sys-color-success: #1b6d2e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 0;
      font-family: 'Roboto', sans-serif;
      background: var(--md-sys-color-surface);
      color: var(--md-sys-color-on-surface);
    }
    .top-app-bar {
      background: var(--md-sys-color-primary-container);
      color: var(--md-sys-color-on-primary-container);
      padding: 16px 24px;
      display: flex; align-items: center; gap: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
    .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
    .card {
      background: #ffffff;
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 16px; padding: 24px; margin-bottom: 24px;
    }
    .card-title {
      font-size: 1.2rem; font-weight: 500; display: flex; align-items: center; gap: 8px;
      margin-bottom: 16px; color: var(--md-sys-color-primary);
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .field { margin-bottom: 16px; }
    .field label { display: block; font-size: 0.85rem; color: var(--md-sys-color-outline); margin-bottom: 6px; font-weight: 500; }
    .field input, .field textarea {
      width: 100%; padding: 12px; border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 8px; font-size: 0.95rem; font-family: monospace; background: var(--md-sys-color-surface);
    }
    .channel-box {
      background: var(--md-sys-color-surface-container);
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: 12px; padding: 16px; margin-bottom: 16px;
    }
    .btn {
      display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px;
      border-radius: 8px; border: none; background: var(--md-sys-color-primary);
      color: #ffffff; font-weight: 500; cursor: pointer;
    }
    .btn-secondary { background: var(--md-sys-color-surface-container-high); color: var(--md-sys-color-primary); border: 1px solid var(--md-sys-color-outline-variant); }
    .btn-danger { background: var(--md-sys-color-error); color: #ffffff; }
    .switch-container {
      display: flex; align-items: center; gap: 10px; padding: 12px;
      background: var(--md-sys-color-primary-container); border-radius: 8px; margin-bottom: 16px;
    }
    .action-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; }
  </style>
</head>
<body>
  <div class="top-app-bar">
    <span class="material-symbols-outlined">security</span>
    <span style="font-size: 1.25rem; font-weight: 700;">M3 超级输入防御网关控制中心</span>
  </div>

  <div class="container">
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">shield</span> 协议层物理级超级防御与硬锁死控制
      </div>
      <div class="switch-container">
        <input type="checkbox" id="enable_super_shield" style="width: 20px; height: 20px;">
        <label for="enable_super_shield" style="font-weight: 700; color: var(--md-sys-color-on-primary-container); cursor: pointer;">
          开启全局物理防御（粉碎 Tools、剥离 System 人设、丢弃历史上下文，将输入严格锁定至指定字数）
        </label>
      </div>
      <div class="grid">
        <div class="field">
          <label>自定义输入锁死字符上限 (超过直接硬切)</label>
          <input type="number" id="custom_input_clamp_chars">
        </div>
        <div class="field">
          <label>自定义输出锁死 Max Tokens (上游生成达标强制截停)</label>
          <input type="number" id="custom_output_max_tokens">
        </div>
        <div class="field">
          <label>覆盖 Temperature 温度</label>
          <input type="number" step="0.1" id="override_temperature">
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="material-symbols-outlined">key</span> 访问密钥鉴权</div>
      <div class="grid">
        <div class="field">
          <label>控制台管理员密钥</label>
          <input type="text" id="admin_key">
        </div>
        <div class="field">
          <label>允许客户端调用的 API Keys (每行一个)</label>
          <textarea rows="3" id="allowed_client_keys"></textarea>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="material-symbols-outlined">hub</span> 上游调度渠道</div>
      <div id="channelContainer"></div>
      <div class="action-bar">
        <button class="btn" onclick="addChannel()"><span class="material-symbols-outlined">add</span> 添加渠道</button>
        <button class="btn" onclick="saveAll()"><span class="material-symbols-outlined">save</span> 立即热同步生效</button>
      </div>
    </div>
  </div>

  <script>
    let configState = {
      security: { admin_key: "sk-admin-root", allowed_client_keys: ["sk-astrbot-client-key"] },
      shield_limits: { enable_super_shield: true, custom_input_clamp_chars: 40, custom_output_max_tokens: 40, override_temperature: 0.2 },
      channels: []
    };

    async function loadConfig() {
      try {
        const res = await fetch('/_admin/api/config');
        const data = await res.json();
        configState = data;

        const s = configState.shield_limits || configState.global_limits || {};
        const sec = configState.security || {};

        document.getElementById('enable_super_shield').checked = s.enable_super_shield ?? true;
        document.getElementById('custom_input_clamp_chars').value = s.custom_input_clamp_chars ?? s.max_total_input_chars ?? 40;
        document.getElementById('custom_output_max_tokens').value = s.custom_output_max_tokens ?? s.force_max_output_tokens ?? 40;
        document.getElementById('override_temperature').value = s.override_temperature ?? 0.2;

        document.getElementById('admin_key').value = sec.admin_key || 'sk-admin-root';
        document.getElementById('allowed_client_keys').value = (sec.allowed_client_keys || ['sk-astrbot-client-key']).join('\\n');

        if (!configState.channels || configState.channels.length === 0) {
          configState.channels = [{
            id: "ch-default-1",
            name: "OpenAI Labs Gemini",
            active: true,
            base_url: "https://www.openai-labs.com",
            api_key: "",
            models: ["gemini-2.5-flash-lite"],
            model_mapping: {}
          }];
        }

        renderChannels();
      } catch (err) {
        console.error("加载配置失败:", err);
      }
    }

    function renderChannels() {
      const box = document.getElementById('channelContainer');
      box.innerHTML = '';
      (configState.channels || []).forEach((ch, idx) => {
        box.innerHTML += `
          <div class="channel-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px;">
              <strong>${ch.name || '渠道'}</strong>
              <div style="display: flex; gap: 8px;">
                <button class="btn btn-secondary" style="padding: 4px 10px;" onclick="testChannel(${idx})">
                  <span class="material-symbols-outlined" style="font-size:18px;">network_check</span> 测试连通性
                </button>
                <button class="btn btn-danger" style="padding: 4px 8px;" onclick="removeChannel(${idx})">
                  <span class="material-symbols-outlined" style="font-size:18px;">delete</span>
                </button>
              </div>
            </div>
            <div class="grid">
              <div class="field">
                <label>通道名称</label>
                <input value="${ch.name || ''}" oninput="configState.channels[${idx}].name = this.value">
              </div>
              <div class="field">
                <label>上游 Base URL (不要带末尾斜杠)</label>
                <input value="${ch.base_url || ''}" oninput="configState.channels[${idx}].base_url = this.value">
              </div>
              <div class="field">
                <label>上游 API Key</label>
                <input type="password" value="${ch.api_key || ''}" oninput="configState.channels[${idx}].api_key = this.value">
              </div>
              <div class="field">
                <label>支持模型 (逗号分隔)</label>
                <input value="${(ch.models || []).join(',')}" oninput="configState.channels[${idx}].models = this.value.split(',').map(s => s.trim())">
              </div>
            </div>
            <div id="test-result-${idx}" style="font-size: 0.85rem; margin-top: 8px; font-family: monospace;"></div>
          </div>
        `;
      });
    }

    function addChannel() {
      if (!configState.channels) configState.channels = [];
      configState.channels.push({
        id: "ch-" + Math.random().toString(36).substring(7),
        name: "新建渠道",
        active: true,
        base_url: "https://www.openai-labs.com",
        api_key: "",
        models: ["gemini-2.5-flash-lite"],
        model_mapping: {}
      });
      renderChannels();
    }

    function removeChannel(idx) {
      configState.channels.splice(idx, 1);
      renderChannels();
    }

    async function testChannel(idx) {
      const resultBox = document.getElementById(`test-result-${idx}`);
      resultBox.innerHTML = '<span style="color: var(--md-sys-color-primary);">正在测试连通性...</span>';
      try {
        const res = await fetch('/_admin/api/test_channel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            base_url: configState.channels[idx].base_url,
            api_key: configState.channels[idx].api_key,
            model: (configState.channels[idx].models && configState.channels[idx].models[0]) || "gemini-2.5-flash-lite"
          })
        });
        const data = await res.json();
        if (data.status === 'success') {
          resultBox.innerHTML = `<span style="color: var(--md-sys-color-success);">[通过] 连通正常！耗时: ${data.latency_ms}ms | 响应: "${data.reply}"</span>`;
        } else {
          resultBox.innerHTML = `<span style="color: var(--md-sys-color-error);">[失败] 状态码 ${data.status_code}: ${data.error}</span>`;
        }
      } catch (err) {
        resultBox.innerHTML = `<span style="color: var(--md-sys-color-error);">[异常] ${err.message}</span>`;
      }
    }

    async function saveAll() {
      configState.shield_limits = {
        enable_super_shield: document.getElementById('enable_super_shield').checked,
        custom_input_clamp_chars: parseInt(document.getElementById('custom_input_clamp_chars').value) || 40,
        custom_output_max_tokens: parseInt(document.getElementById('custom_output_max_tokens').value) || 40,
        override_temperature: parseFloat(document.getElementById('override_temperature').value) || 0.2
      };

      configState.security = {
        admin_key: document.getElementById('admin_key').value,
        allowed_client_keys: document.getElementById('allowed_client_keys').value.split('\\n').map(s => s.trim()).filter(s => s.length > 0)
      };

      await fetch('/_admin/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configState)
      });
      alert('超级防御策略与渠道配置已成功热保存！');
    }

    loadConfig();
  </script>
</body>
</html>
"""

async def admin_page(request): return web.Response(text=HTML_UI, content_type='text/html')
async def get_config_api(request): return web.json_response(db)

async def post_config_api(request):
    global db
    db = await request.json()
    save_data(db)
    print(">>> [SHIELD-CONFIG] 页面保存成功，配置与渠道已成功持久化至本地硬盘。")
    return web.json_response({"status": "ok"})

async def test_channel_api(request):
    try:
        data = await request.json()
        base_url = data.get("base_url", "").rstrip('/')
        api_key = data.get("api_key", "")
        model = data.get("model", "gemini-2.5-flash-lite")

        test_payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{base_url}/v1/chat/completions", headers=headers, json=test_payload) as resp:
                latency = int((time.time() - start_time) * 1000)
                if resp.status == 200:
                    res_json = await resp.json()
                    reply = res_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    return web.json_response({"status": "success", "latency_ms": latency, "reply": reply})
                else:
                    return web.json_response({"status": "error", "status_code": resp.status, "error": (await resp.text())[:200]})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})

async def models_handler(request):
    model_list = []
    for ch in db.get("channels", []):
        if ch.get("active", True):
            for m in ch.get("models", []):
                model_list.append({"id": m, "object": "model", "owned_by": "m3-gateway"})
    return web.json_response({"object": "list", "data": model_list})

async def chat_handler(request):
    auth_header = request.headers.get("Authorization", "")
    client_token = auth_header.replace("Bearer ", "").strip()
    allowed_keys = db.get("security", {}).get("allowed_client_keys", [])
    admin_key = db.get("security", {}).get("admin_key", "")

    if allowed_keys and (client_token not in allowed_keys and client_token != admin_key):
        return web.json_response({"error": {"message": "Invalid Client API Key"}}, status=401)

    try:
        req_data = await request.json()
    except Exception:
        return web.json_response({"error": {"message": "Invalid JSON Body"}}, status=400)

    req_model = req_data.get("model", "")
    matched_channels = [ch for ch in db.get("channels", []) if ch.get("active", True)]
    if not matched_channels:
        return web.json_response({"error": {"message": "No active upstream channels configured"}}, status=503)

    target_ch = random.choice(matched_channels)
    req_data["model"] = target_ch.get("model_mapping", {}).get(req_model, req_model)

    req_data.pop("tools", None)
    req_data.pop("functions", None)
    req_data.pop("tool_choice", None)

    shield = db.get("shield_limits", db.get("global_limits", {}))
    enable_shield = shield.get("enable_super_shield", True)
    input_clamp = shield.get("custom_input_clamp_chars", shield.get("max_total_input_chars", 40))
    output_clamp = shield.get("custom_output_max_tokens", shield.get("force_max_output_tokens", 40))

    if enable_shield:
        user_text = ""
        if "messages" in req_data and isinstance(req_data["messages"], list):
            for msg in reversed(req_data["messages"]):
                if msg.get("role") == "user":
                    user_text = sanitize_text(msg.get("content", ""))
                    break
        
        clamped_text = user_text[:input_clamp]
        req_data["messages"] = [{"role": "user", "content": clamped_text}]

    req_data["max_tokens"] = output_clamp
    req_data["temperature"] = shield.get("override_temperature", 0.2)

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
    app.router.add_get('/', admin_page)
    app.router.add_get('/_admin', admin_page)
    app.router.add_get('/_admin/api/config', get_config_api)
    app.router.add_post('/_admin/api/config', post_config_api)
    app.router.add_post('/_admin/api/test_channel', test_channel_api)
    app.router.add_get('/v1/models', models_handler)
    app.router.add_post('/v1/chat/completions', chat_handler)
    return app

if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=DEFAULT_PORT)
