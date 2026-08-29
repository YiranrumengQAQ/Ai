#!/usr/bin/env python3
"""
M3 Dynamic Aggregation Gateway & Control Center
Features:
- Total Prompt Hard-Clamping (Stripping System/Persona Bloat down to exact limit)
- Real-time Channel Connectivity & Ping Testing
- Dynamic Upstream Model Mapping & Load Balancing
- Zero-Downtime Hot Reloading
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
    "global_limits": {
        "enable_total_prompt_hard_clamp": True,  # 无论 AstrBot 人设多长，强行将最终发送给模型的全量输入总字数切断
        "max_total_input_chars": 40,             # 限制总输入字符数 (含人设+用户输入)
        "force_max_input_chars": 40,             # 单条用户消息限制
        "force_max_output_tokens": 40,           # 单次回复 Token 限制
        "keep_last_n_messages": 1,               # 历史上下文保留轮数
        "override_temperature": 0.2
    },
    "channels": [
        {
            "id": "ch-default-1",
            "name": "OpenAI / Gemini 聚合通道",
            "active": True,
            "base_url": "https://api.openai.com",
            "api_key": "sk-your-actual-api-key-here",
            "models": ["gpt-4o-mini", "gpt-3.5-turbo", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
            "model_mapping": {
                "openai/gemini-2.5-flash-lite": "gemini-2.5-flash-lite"
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
      --md-sys-color-success: #1b6d2e;
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
    .btn-secondary {
      background: var(--md-sys-color-surface-container-high);
      color: var(--md-sys-color-primary);
      border: 1px solid var(--md-sys-color-outline-variant);
    }
    .btn-danger {
      background: var(--md-sys-color-error);
      color: #ffffff;
    }
    .switch-container {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px;
      background: var(--md-sys-color-primary-container);
      border-radius: 8px;
      margin-bottom: 16px;
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
    <!-- 全局防刷与输入输出终极物理锁 -->
    <div class="card">
      <div class="card-title">
        <span class="material-symbols-outlined">lock_clock</span> 全局输入硬锁死 & 输出 Token 限制
      </div>

      <div class="switch-container">
        <input type="checkbox" id="enable_total_prompt_hard_clamp" style="width: 20px; height: 20px;">
        <label for="enable_total_prompt_hard_clamp" style="font-weight: 700; color: var(--md-sys-color-on-primary-container); cursor: pointer;">
          开启全局全量输入强制锁死（强行剥离 AstrBot 系统人设与提示词臃肿，总字数强行压缩）
        </label>
      </div>

      <div class="grid">
        <div class="field">
          <label>全量输入字符硬上限 (开启上方开关后生效，无论人设多长直接硬切)</label>
          <input type="number" id="max_total_input_chars">
        </div>
        <div class="field">
          <label>单次输出物理锁定 Max Tokens</label>
          <input type="number" id="force_max_output_tokens">
        </div>
        <div class="field">
          <label>单条用户消息最大限制 (字符)</label>
          <input type="number" id="force_max_input_chars">
        </div>
        <div class="field">
          <label>历史上下文强制保留轮数 (设为 1 杜绝历史叠加)</label>
          <input type="number" id="keep_last_n_messages">
        </div>
      </div>
    </div>

    <!-- 鉴权密钥 -->
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
        <span class="material-symbols-outlined">account_tree</span> 上游模型聚合调度渠道 (支持一键连通性测试)
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

      document.getElementById('enable_total_prompt_hard_clamp').checked = configState.global_limits.enable_total_prompt_hard_clamp;
      document.getElementById('max_total_input_chars').value = configState.global_limits.max_total_input_chars || 40;
      document.getElementById('force_max_output_tokens').value = configState.global_limits.force_max_output_tokens;
      document.getElementById('force_max_input_chars').value = configState.global_limits.force_max_input_chars;
      document.getElementById('keep_last_n_messages').value = configState.global_limits.keep_last_n_messages;

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
            <div id="test-result-${idx}" style="font-size: 0.85rem; margin-top: 8px; font-family: monospace;"></div>
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
        models: ["gpt-4o-mini", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
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
      resultBox.innerHTML = '<span style="color: var(--md-sys-color-primary);">正在测试上游连通性并计算延迟...</span>';
      
      const payload = {
        base_url: configState.channels[idx].base_url,
        api_key: configState.channels[idx].api_key,
        model: configState.channels[idx].models[0] || "gpt-4o-mini"
      };

      try {
        const res = await fetch('/_admin/api/test_channel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
          resultBox.innerHTML = `<span style="color: var(--md-sys-color-success);">[通过] 连接正常！耗时: ${data.latency_ms}ms | 上游回复: "${data.reply}"</span>`;
        } else {
          resultBox.innerHTML = `<span style="color: var(--md-sys-color-error);">[失败] 报错代码 ${data.status_code}: ${data.error}</span>`;
        }
      } catch (err) {
        resultBox.innerHTML = `<span style="color: var(--md-sys-color-error);">[网络异常] 无法连接到测试端点: ${err.message}</span>`;
      }
    }

    async function saveAll() {
      configState.global_limits.enable_total_prompt_hard_clamp = document.getElementById('enable_total_prompt_hard_clamp').checked;
      configState.global_limits.max_total_input_chars = parseInt(document.getElementById('max_total_input_chars').value) || 40;
      configState.global_limits.force_max_output_tokens = parseInt(document.getElementById('force_max_output_tokens').value) || 40;
      configState.global_limits.force_max_input_chars = parseInt(document.getElementById('force_max_input_chars').value) || 40;
      configState.global_limits.keep_last_n_messages = parseInt(document.getElementById('keep_last_n_messages').value) || 1;

      configState.security.admin_key = document.getElementById('admin_key').value;
      configState.security.allowed_client_keys = document.getElementById('allowed_client_keys').value.split('\\n').filter(s => s.trim().length > 0);

      await fetch('/_admin/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configState)
      });
      alert('网关配置已更新并实时热生效！');
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
    print(">>> [CONFIG] 网关配置已被管理面板热更新并重载。")
    return web.json_response({"status": "ok"})

async def test_channel_api(request):
    try:
        data = await request.json()
        base_url = data.get("base_url", "").rstrip('/')
        api_key = data.get("api_key", "")
        model = data.get("model", "gpt-4o-mini")

        test_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{base_url}/v1/chat/completions", headers=headers, json=test_payload) as resp:
                latency = int((time.time() - start_time) * 1000)
                if resp.status == 200:
                    res_json = await resp.json()
                    reply = res_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    return web.json_response({
                        "status": "success",
                        "latency_ms": latency,
                        "reply": reply
                    })
                else:
                    err_text = await resp.text()
                    return web.json_response({
                        "status": "error",
                        "status_code": resp.status,
                        "error": err_text[:200]
                    })
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
        print(f"[AUTH-DENY] 非法客户端 Token 请求: {client_token}")
        return web.json_response({"error": {"message": "Invalid Client API Key", "type": "auth_error"}}, status=401)

    try:
        req_data = await request.json()
    except Exception:
        return web.json_response({"error": {"message": "Invalid JSON Body"}}, status=400)

    req_model = req_data.get("model", "")
    matched_channels = []
    for ch in db.get("channels", []):
        if ch.get("active", True):
            if req_model in ch.get("models", []) or req_model in ch.get("model_mapping", {}):
                matched_channels.append(ch)

    if not matched_channels:
        matched_channels = [ch for ch in db.get("channels", []) if ch.get("active", True)]
    
    if not matched_channels:
        print(f"[ERROR] 未能为模型 {req_model} 找到任何可用上游渠道！")
        return web.json_response({"error": {"message": f"No available upstream channel for model {req_model}"}}, status=503)

    target_ch = random.choice(matched_channels)
    final_model = target_ch.get("model_mapping", {}).get(req_model, req_model)
    req_data["model"] = final_model

    # 核心拦截与强力硬切
    limits = db.get("global_limits", {})
    enable_total_clamp = limits.get("enable_total_prompt_hard_clamp", True)
    max_total_chars = limits.get("max_total_input_chars", 40)
    max_in = limits.get("force_max_input_chars", 40)
    max_out = limits.get("force_max_output_tokens", 40)
    keep_n = limits.get("keep_last_n_messages", 1)

    print("\n==================== [M3 GATEWAY INBOUND REQUEST] ====================")
    print(f"[*] 收到请求模型: {req_model} -> 映射为上游模型: {final_model}")

    if "messages" in req_data and isinstance(req_data["messages"], list):
        orig_msg_count = len(req_data["messages"])

        # 终极策略：如果开启了全量输入锁死，将整个 messages 中的 System/User 文本强行压制在指定字数内
        if enable_total_clamp:
            # 仅提取最后一条 user 消息
            user_msgs = [m for m in req_data["messages"] if m.get("role") == "user"]
            latest_content = user_msgs[-1].get("content", "") if user_msgs else ""
            
            # 彻底干掉 AstrBot 附带的几百字 System 人设，只保留一条极简 user 消息并物理切断
            clamped_content = str(latest_content)[:max_total_chars]
            req_data["messages"] = [{"role": "user", "content": clamped_content}]
            print(f"[!] 触发全量输入硬锁死 (彻底剥离人设): 原始 {orig_msg_count} 条消息已强行精炼为 1 条并硬切至 {max_total_chars} 字符:")
            print(f"    最终送模内容: \"{clamped_content}\"")
        else:
            # 普通策略：按轮数和单条字数裁剪
            if orig_msg_count > keep_n:
                req_data["messages"] = req_data["messages"][-keep_n:]
                print(f"[!] 历史上下文压缩: 裁剪为最近 {len(req_data['messages'])} 条")

            last_msg = req_data["messages"][-1]
            content = last_msg.get("content", "")
            if isinstance(content, str) and max_in > 0 and len(content) > max_in:
                last_msg["content"] = content[:max_in]
                print(f"[!] 触发单条输入截断: 截断为前 {max_in} 字符: {last_msg['content']}")

    # 强制锁死输出 max_tokens
    req_data["max_tokens"] = max_out
    print(f"[*] 输出 Tokens 物理锁定为: {max_out}")
    print(f"[*] 转发目标渠道: {target_ch['name']} ({target_ch['base_url']})")
    print("======================================================================")

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
            print(f"[ERROR] 上游调用失败: {str(e)}")
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
