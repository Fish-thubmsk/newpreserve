#!/usr/bin/env python3
"""
config_wizard.py — 本地 Web 可视化配置向导

通过内置的轻量级 Flask 服务，代理超星图书馆座位预约 API，
提供交互式选座 UI，引导用户完成 config/config.yml 的自动生成。

使用方法：
    python config_wizard.py

然后在浏览器打开 http://127.0.0.1:5000，按页面提示操作。
"""

import os
import sys
import json
import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] 缺少依赖 pyyaml，请运行：pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[ERROR] 缺少依赖 requests，请运行：pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERROR] 缺少依赖 python-dotenv，请运行：pip install -r requirements.txt")
    sys.exit(1)

try:
    from flask import Flask, request, jsonify, render_template_string
except ImportError:
    print("[ERROR] 缺少依赖 flask，请运行：pip install -r requirements.txt")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
API_BASE = "https://office.chaoxing.com"
REQUEST_TIMEOUT = 15

app = Flask(__name__)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_cookie() -> str:
    """从 .env 文件加载 Cookie（若存在）。"""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        cookie = os.getenv("CX_COOKIE", "").strip().strip('"').strip("'")
        if cookie and not cookie.startswith("UID=xxx"):
            return cookie
    return ""


def make_session(cookie: str) -> requests.Session:
    """创建带有 Cookie 及常用请求头的 Session。"""
    session = requests.Session()
    session.headers.update(
        {
            "Cookie": cookie,
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; Mobile) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
            "Referer": f"{API_BASE}/front/third/apps/seat/select",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    return session


def proxy_get(path: str, params: dict, cookie: str) -> tuple:
    """代理一个 GET 请求到官方 API，返回 (json_data, error_str)。"""
    session = make_session(cookie)
    url = f"{API_BASE}/{path.lstrip('/')}"
    try:
        resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return None, "请求超时，请检查网络连接"
    except requests.exceptions.ConnectionError as e:
        return None, f"网络连接错误：{e}"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP 错误：{e}"

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type or resp.text.strip().startswith("<!DOCTYPE"):
        return None, "Cookie 已失效，请在页面上重新填写有效的 Cookie"

    try:
        return resp.json(), None
    except ValueError:
        return None, f"响应格式错误（非 JSON）：{resp.text[:200]}"


# ---------------------------------------------------------------------------
# Flask 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """配置向导主页。"""
    return render_template_string(_HTML_TEMPLATE)


@app.route("/api/levels")
def api_levels():
    """代理：获取楼层列表（一级/二级/三级）。

    上游 API 参数说明：
      type=0  返回一级（校区）列表
      type=1  返回二级（楼层）列表，需同时传 firstLevelName
      type=2  返回三级（区域）列表，需同时传 firstLevelName + secondLevelName
    """
    cookie = request.args.get("cookie", "").strip() or load_cookie()
    dept_id_enc = request.args.get("deptIdEnc", "")
    level_type = request.args.get("type", "0")
    first_level = request.args.get("firstLevel", "")
    second_level = request.args.get("secondLevel", "")
    if level_type not in ("0", "1", "2"):
        return jsonify({"success": False, "msg": "type 参数无效，可选值为 0、1、2"}), 400
    if level_type == "1" and not first_level:
        return jsonify({"success": False, "msg": "type=1 时必须提供 firstLevel 参数"}), 400
    if level_type == "2" and not (first_level and second_level):
        return jsonify({"success": False, "msg": "type=2 时必须同时提供 firstLevel 和 secondLevel 参数"}), 400
    params = {"type": level_type}
    if dept_id_enc:
        params["deptIdEnc"] = dept_id_enc
    if first_level:
        params["firstLevelName"] = first_level
    if second_level:
        params["secondLevelName"] = second_level
    data, err = proxy_get("/data/apps/seat/levels", params, cookie)
    if err:
        return jsonify({"success": False, "msg": err}), 502
    return jsonify(data)


@app.route("/api/rooms")
def api_rooms():
    """代理：获取阅览室列表。"""
    cookie = request.args.get("cookie", "").strip() or load_cookie()
    dept_id_enc = request.args.get("deptIdEnc", "")
    first_level = request.args.get("firstLevel", "")
    second_level = request.args.get("secondLevel", "")
    third_level = request.args.get("thirdLevel", "")
    params = {
        "pageNum": 1,
        "pageSize": 100,
    }
    if dept_id_enc:
        params["deptIdEnc"] = dept_id_enc
    if first_level:
        params["firstLevelName"] = first_level
    if second_level:
        params["secondLevelName"] = second_level
    if third_level:
        params["thirdLevelName"] = third_level
    data, err = proxy_get("/data/apps/seat/room/list", params, cookie)
    if err:
        return jsonify({"success": False, "msg": err}), 502
    return jsonify(data)


@app.route("/api/seatgrid")
def api_seatgrid():
    """代理：获取某房间的座位布局及状态。"""
    cookie = request.args.get("cookie", "").strip() or load_cookie()
    room_id = request.args.get("roomId", "")
    dept_id_enc = request.args.get("deptIdEnc", "")
    start_time = request.args.get("startTime", "")
    end_time = request.args.get("endTime", "")
    if not room_id:
        return jsonify({"success": False, "msg": "缺少参数 roomId"}), 400
    params = {"roomId": room_id}
    if dept_id_enc:
        params["deptIdEnc"] = dept_id_enc
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    data, err = proxy_get("/data/apps/seat/seatgrid/roomid", params, cookie)
    if err:
        return jsonify({"success": False, "msg": err}), 502
    return jsonify(data)


@app.route("/api/save-config", methods=["POST"])
def api_save_config():
    """接收前端发来的选座结果，写入 config/config.yml。"""
    payload = request.get_json(force=True, silent=True) or {}

    seat_ids = payload.get("seatIds", [])
    dept_id_enc = payload.get("deptIdEnc", "")
    room_id = payload.get("roomId")
    first_level = payload.get("firstLevel", "")
    second_level = payload.get("secondLevel", "")
    third_level = payload.get("thirdLevel", "")
    start_time = payload.get("startTime", "08:00")
    end_time = payload.get("endTime", "22:30")
    target_date_mode = payload.get("targetDateMode", "tomorrow")
    target_date = payload.get("targetDate", "")

    if not seat_ids:
        return jsonify({"success": False, "msg": "未选择任何座位"}), 400
    if not dept_id_enc:
        return jsonify({"success": False, "msg": "缺少 deptIdEnc 参数"}), 400

    # 读取现有配置（若存在）以保留其他字段
    config_path = BASE_DIR / "config" / "config.yml"
    existing: dict = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    # 构建新配置（保留 behavior / logging 等已有字段）
    new_cfg: dict = {
        "target_date_mode": target_date_mode,
        "target_date": target_date or (
            datetime.date.today() + datetime.timedelta(days=1)
        ).strftime("%Y-%m-%d"),
        "time_range": {
            "start": start_time,
            "end": end_time,
        },
        "seat_ids": [int(sid) for sid in seat_ids],
        "area": {
            "dept_id_enc": dept_id_enc,
            "room_id": int(room_id) if room_id and str(room_id).isdigit() else None,
            "first_level": first_level,
            "second_level": second_level,
            "third_level": third_level,
        },
        "behavior": existing.get(
            "behavior",
            {
                "max_seats_to_try": 5,
                "interval_seconds_between_seats": 0.2,
            },
        ),
        "logging": existing.get(
            "logging",
            {
                "level": "INFO",
                "file": "reserve.log",
            },
        ),
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            new_cfg,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    return jsonify({"success": True, "msg": f"配置已写入 {config_path}"})


# ---------------------------------------------------------------------------
# 前端 HTML 模板（内联，避免引入额外的 templates/ 目录）
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>超星图书馆 · 配置向导</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #333; min-height: 100vh; }
  header { background: #1a6fc4; color: #fff; padding: 18px 24px; }
  header h1 { font-size: 1.25rem; font-weight: 700; }
  header p  { font-size: 0.85rem; opacity: .85; margin-top: 4px; }
  .container { max-width: 900px; margin: 28px auto; padding: 0 16px 48px; }
  .card { background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,.08); padding: 24px; margin-bottom: 20px; }
  .card h2 { font-size: 1rem; font-weight: 700; margin-bottom: 16px; color: #1a6fc4; border-left: 3px solid #1a6fc4; padding-left: 10px; }
  label { display: block; font-size: .875rem; color: #555; margin-bottom: 5px; font-weight: 500; }
  input[type=text], input[type=time], input[type=date], select {
    width: 100%; padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px;
    font-size: .9rem; outline: none; transition: border .2s;
  }
  input:focus, select:focus { border-color: #1a6fc4; }
  .field { margin-bottom: 14px; }
  .row { display: flex; gap: 14px; }
  .row .field { flex: 1; }
  .btn { display: inline-block; padding: 9px 22px; border: none; border-radius: 6px; font-size: .9rem; cursor: pointer; font-weight: 600; transition: opacity .15s; }
  .btn-primary { background: #1a6fc4; color: #fff; }
  .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
  .btn-success { background: #27ae60; color: #fff; }
  .btn:hover:not(:disabled) { opacity: .85; }

  /* Seat grid */
  #seat-grid-wrap { overflow: auto; }
  #seat-grid { display: grid; gap: 4px; width: max-content; }
  .seat-cell {
    width: 36px; height: 36px; border-radius: 5px; font-size: .65rem; text-align: center;
    line-height: 36px; cursor: pointer; border: 1px solid transparent; user-select: none;
    font-weight: 600;
  }
  .seat-available  { background: #d4edda; color: #155724; border-color: #c3e6cb; }
  .seat-occupied   { background: #e8e8e8; color: #999;    border-color: #d6d6d6; cursor: not-allowed; }
  .seat-selected   { background: #1a6fc4; color: #fff;    border-color: #155b9e; }
  .seat-obstacle   { background: transparent; border: none; cursor: default; }

  /* Selected list */
  #selected-list { margin-top: 10px; }
  .tag { display: inline-flex; align-items: center; gap: 6px; background: #e8f0fe; color: #1a6fc4; border-radius: 20px; padding: 3px 12px; font-size: .82rem; margin: 3px; }
  .tag .rm { cursor: pointer; color: #888; font-weight: 700; }

  /* Alert */
  .alert { padding: 10px 14px; border-radius: 6px; font-size: .875rem; margin-top: 12px; }
  .alert-info    { background: #d1ecf1; color: #0c5460; }
  .alert-success { background: #d4edda; color: #155724; }
  .alert-error   { background: #f8d7da; color: #721c24; }

  .loading { color: #888; font-size: .875rem; }
  #step2, #step3, #step4 { display: none; }
</style>
</head>
<body>

<header>
  <h1>🪑 超星图书馆座位配置向导</h1>
  <p>通过可视化界面选座，自动生成 config/config.yml，无需手动抓包</p>
</header>

<div class="container">

<!-- STEP 1: Cookie & DeptIdEnc -->
<div class="card" id="step1">
  <h2>Step 1 · 输入认证信息</h2>
  <div class="field">
    <label>Cookie（从浏览器 DevTools 复制，若已在 .env 中配置可留空）</label>
    <input type="text" id="cookie-input" placeholder="UID=xxx; JSESSIONID=xxx; fid=xxx; ..." />
  </div>
  <div class="field">
    <label>deptIdEnc（学校加密标识，从 office.chaoxing.com 页面 JS 或抓包中获取）</label>
    <input type="text" id="dept-id-enc-input" placeholder="例如：4a18e12602b24c8c" />
  </div>
  <button class="btn btn-primary" id="btn-load-levels">加载楼层列表 →</button>
  <div id="step1-msg"></div>
</div>

<!-- STEP 2: Level & Room -->
<div class="card" id="step2">
  <h2>Step 2 · 选择区域与阅览室</h2>
  <div class="row">
    <div class="field">
      <label>校区（一级）</label>
      <select id="first-level-select"><option value="">-- 请选择 --</option></select>
    </div>
    <div class="field">
      <label>楼层（二级）</label>
      <select id="second-level-select" disabled><option value="">-- 请先选校区 --</option></select>
    </div>
  </div>
  <div class="field">
    <label>区域（三级）</label>
    <select id="third-level-select" disabled><option value="">-- 请先选楼层 --</option></select>
  </div>
  <div class="field">
    <label>阅览室</label>
    <select id="room-select" disabled><option value="">-- 请先选区域 --</option></select>
  </div>
  <div id="step2-msg"></div>
</div>

<!-- STEP 3: Time range -->
<div class="card" id="step3">
  <h2>Step 3 · 选择预约日期与时间段</h2>
  <div class="row">
    <div class="field">
      <label>日期模式</label>
      <select id="date-mode-select">
        <option value="tomorrow" selected>明天（推荐，配合定时任务使用）</option>
        <option value="date">指定日期</option>
      </select>
    </div>
    <div class="field" id="date-field" style="display:none">
      <label>具体日期</label>
      <input type="date" id="target-date-input" />
    </div>
  </div>
  <div class="row">
    <div class="field">
      <label>开始时间</label>
      <input type="time" id="start-time-input" value="08:00" />
    </div>
    <div class="field">
      <label>结束时间</label>
      <input type="time" id="end-time-input" value="22:30" />
    </div>
  </div>
  <button class="btn btn-primary" id="btn-load-seats" disabled>加载座位布局 →</button>
  <div id="step3-msg"></div>
</div>

<!-- STEP 4: Seat grid -->
<div class="card" id="step4">
  <h2>Step 4 · 点选座位（可多选，按顺序尝试）</h2>
  <div class="alert alert-info">
    🟢 可预约 &nbsp;|&nbsp; ⬛ 已占用 &nbsp;|&nbsp; 🔵 已选中（点击取消）
  </div>
  <div id="seat-grid-wrap" style="margin-top:14px">
    <p class="loading">正在加载座位布局…</p>
  </div>
  <div id="selected-list"></div>
  <div style="margin-top:16px">
    <button class="btn btn-success" id="btn-save" disabled>✅ 保存配置到 config/config.yml</button>
  </div>
  <div id="step4-msg"></div>
</div>

</div><!-- /container -->

<script>
'use strict';

// ---- Utility ----
const $ = id => document.getElementById(id);
const show = id => $(id).style.display = '';
const hide = id => $(id).style.display = 'none';
function setMsg(id, msg, type='info') {
  const el = $(id);
  el.innerHTML = msg ? `<div class="alert alert-${type}" style="margin-top:10px">${msg}</div>` : '';
}
async function apiFetch(url) {
  const resp = await fetch(url);
  const json = await resp.json();
  if (!resp.ok || json.success === false) throw new Error(json.msg || '请求失败');
  return json;
}

// ---- State ----
let state = {
  cookie: '',
  deptIdEnc: '',
  firstLevel: '',
  secondLevel: '',
  roomId: null,
  thirdLevel: '',
  roomName: '',
  startTime: '08:00',
  endTime: '22:30',
  dateMode: 'tomorrow',
  targetDate: '',
  selectedSeats: [],   // [{id, seatNum}]
  allLevels: [],
  allRooms: [],
};

// ---- Step 1: load levels ----
$('btn-load-levels').addEventListener('click', async () => {
  const cookie = $('cookie-input').value.trim();
  const deptIdEnc = $('dept-id-enc-input').value.trim();
  if (!deptIdEnc) { setMsg('step1-msg', '请填写 deptIdEnc', 'error'); return; }

  setMsg('step1-msg', '加载中…', 'info');
  $('btn-load-levels').disabled = true;

  const params = new URLSearchParams({ deptIdEnc, type: 0 });
  if (cookie) params.set('cookie', cookie);

  try {
    const data = await apiFetch(`/api/levels?${params}`);
    state.cookie = cookie;
    state.deptIdEnc = deptIdEnc;
    state.allLevels = data.data?.levels || [];

    // Populate first-level select
    const fs = $('first-level-select');
    fs.innerHTML = '<option value="">-- 请选择 --</option>';
    const firsts = [...new Set(state.allLevels.map(l => l.firstLevelName).filter(Boolean))];
    firsts.forEach(f => fs.add(new Option(f, f)));

    show('step2');
    setMsg('step1-msg', `成功获取楼层数据（${firsts.length} 个校区）`, 'success');
  } catch(e) {
    setMsg('step1-msg', e.message, 'error');
  } finally {
    $('btn-load-levels').disabled = false;
  }
});

// ---- Step 2: first level -> second level ----
$('first-level-select').addEventListener('change', async () => {
  const first = $('first-level-select').value;
  state.firstLevel = first;
  const ss = $('second-level-select');
  ss.innerHTML = '<option value="">-- 请选择 --</option>';
  ss.disabled = !first;
  $('third-level-select').innerHTML = '<option value="">-- 请先选楼层 --</option>';
  $('third-level-select').disabled = true;
  $('room-select').innerHTML = '<option value="">-- 请先选区域 --</option>';
  $('room-select').disabled = true;
  $('btn-load-seats').disabled = true;
  hide('step3');
  hide('step4');
  setMsg('step2-msg', '');
  if (!first) return;

  setMsg('step2-msg', '加载中…', 'info');
  const params = new URLSearchParams({ deptIdEnc: state.deptIdEnc, firstLevel: first, type: 1 });
  if (state.cookie) params.set('cookie', state.cookie);
  try {
    const data = await apiFetch(`/api/levels?${params}`);
    const levels = data.data?.levels || [];
    const seconds = [...new Set(levels.map(l => l.secondLevelName).filter(Boolean))];
    seconds.forEach(s => ss.add(new Option(s, s)));
    ss.disabled = false;
    setMsg('step2-msg', '');
  } catch(e) {
    setMsg('step2-msg', e.message, 'error');
  }
});

// ---- Step 2: second level -> third level ----
$('second-level-select').addEventListener('change', async () => {
  const second = $('second-level-select').value;
  state.secondLevel = second;
  const ts = $('third-level-select');
  ts.innerHTML = '<option value="">-- 请选择 --</option>';
  ts.disabled = !second;
  $('room-select').innerHTML = '<option value="">-- 请先选区域 --</option>';
  $('room-select').disabled = true;
  $('btn-load-seats').disabled = true;
  hide('step3');
  hide('step4');
  setMsg('step2-msg', '');
  if (!second) return;

  setMsg('step2-msg', '加载中…', 'info');
  const params = new URLSearchParams({ deptIdEnc: state.deptIdEnc, firstLevel: state.firstLevel, secondLevel: second, type: 2 });
  if (state.cookie) params.set('cookie', state.cookie);
  try {
    const data = await apiFetch(`/api/levels?${params}`);
    const levels = data.data?.levels || [];
    const thirds = [...new Set(levels.map(l => l.thirdLevelName).filter(Boolean))];
    thirds.forEach(t => ts.add(new Option(t, t)));
    ts.disabled = false;
    setMsg('step2-msg', '');
  } catch(e) {
    setMsg('step2-msg', e.message, 'error');
  }
});

// ---- Step 2: third level -> rooms ----
$('third-level-select').addEventListener('change', async () => {
  const third = $('third-level-select').value;
  state.thirdLevel = third;
  const rs = $('room-select');
  rs.innerHTML = '<option value="">-- 请选择 --</option>';
  rs.disabled = !third;
  $('btn-load-seats').disabled = true;
  hide('step3');
  hide('step4');
  setMsg('step2-msg', '');
  if (!third) return;

  setMsg('step2-msg', '加载阅览室列表…', 'info');
  const params = new URLSearchParams({
    deptIdEnc: state.deptIdEnc,
    firstLevel: state.firstLevel,
    secondLevel: state.secondLevel,
    thirdLevel: third,
  });
  if (state.cookie) params.set('cookie', state.cookie);
  try {
    const data = await apiFetch(`/api/rooms?${params}`);
    const rooms = data.data?.seatRoomList || [];
    state.allRooms = rooms;
    rooms.forEach(r => {
      const label = r.thirdLevelName || `Room ${r.id}`;
      rs.add(new Option(label, r.id));
    });
    rs.disabled = false;
    setMsg('step2-msg', `共 ${rooms.length} 个阅览室`, 'success');
  } catch(e) {
    setMsg('step2-msg', e.message, 'error');
  }
});

// ---- Step 2: room selected ----
$('room-select').addEventListener('change', () => {
  const rid = $('room-select').value;
  state.roomId = rid || null;
  if (rid) {
    const room = state.allRooms.find(r => String(r.id) === String(rid));
    state.thirdLevel = room?.thirdLevelName || '';
    show('step3');
    $('btn-load-seats').disabled = false;
    hide('step4');
    setMsg('step2-msg', '');
  } else {
    $('btn-load-seats').disabled = true;
    hide('step3');
    hide('step4');
  }
});

// ---- Step 3: date mode ----
$('date-mode-select').addEventListener('change', () => {
  state.dateMode = $('date-mode-select').value;
  if (state.dateMode === 'date') show('date-field');
  else hide('date-field');
});

// ---- Step 3: load seats ----
$('btn-load-seats').addEventListener('click', async () => {
  state.startTime = $('start-time-input').value || '08:00';
  state.endTime   = $('end-time-input').value   || '22:30';
  state.targetDate = $('target-date-input').value || '';
  state.dateMode = $('date-mode-select').value;

  setMsg('step3-msg', '加载座位布局…', 'info');
  $('btn-load-seats').disabled = true;
  $('seat-grid-wrap').innerHTML = '<p class="loading">加载中…</p>';
  state.selectedSeats = [];
  renderSelectedList();
  show('step4');
  setMsg('step4-msg', '');

  // Compute timestamps for the query
  // Use tomorrow's date if dateMode == 'tomorrow'
  let dateStr = state.targetDate;
  if (state.dateMode === 'tomorrow' || !dateStr) {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    dateStr = d.toISOString().slice(0, 10);
  }
  const startMs = dateToMs(dateStr, state.startTime);
  const endMs   = dateToMs(dateStr, state.endTime);

  const params = new URLSearchParams({
    roomId: state.roomId,
    deptIdEnc: state.deptIdEnc,
    startTime: startMs,
    endTime: endMs,
  });
  if (state.cookie) params.set('cookie', state.cookie);

  try {
    const data = await apiFetch(`/api/seatgrid?${params}`);
    renderSeatGrid(data.data);
    setMsg('step3-msg', '');
  } catch(e) {
    setMsg('step3-msg', e.message, 'error');
    $('seat-grid-wrap').innerHTML = `<p style="color:red">${e.message}</p>`;
  } finally {
    $('btn-load-seats').disabled = false;
  }
});

function dateToMs(dateStr, timeStr) {
  // dateStr: YYYY-MM-DD, timeStr: HH:MM — treated as CST (UTC+8)
  // The '+08:00' suffix lets Date correctly convert to UTC milliseconds.
  return new Date(`${dateStr}T${timeStr}:00+08:00`).getTime();
}

// ---- Seat grid rendering ----
function renderSeatGrid(data) {
  if (!data) { $('seat-grid-wrap').innerHTML = '<p>无座位数据</p>'; return; }

  const seatDatas  = data.seatDatas  || [];
  const otherDatas = data.otherDatas || {};
  const cols = (otherDatas.x || 0) + 1;
  const rows = (otherDatas.y || 0) + 1;

  // Build a map: "x,y" -> seat
  const seatMap = {};
  seatDatas.forEach(s => { seatMap[`${s.x},${s.y}`] = s; });

  // Obstacle positions from otherDatas.config
  const obstacles = new Set();
  try {
    const cfg = JSON.parse(otherDatas.config || '[]');
    cfg.forEach(o => obstacles.add(`${o.x},${o.y}`));
  } catch(_) {}

  const grid = document.createElement('div');
  grid.id = 'seat-grid';
  grid.style.gridTemplateColumns = `repeat(${cols}, 36px)`;

  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const key = `${x},${y}`;
      const cell = document.createElement('div');
      cell.className = 'seat-cell';

      if (seatMap[key]) {
        const s = seatMap[key];
        const occupied = s.reserveStatus === 1;
        const selectedIdx = state.selectedSeats.findIndex(ss => ss.id === s.id);
        cell.classList.add(
          selectedIdx >= 0 ? 'seat-selected' :
          occupied        ? 'seat-occupied'  :
                            'seat-available'
        );
        cell.textContent = s.seatNum;
        cell.title = `座位号 ${s.seatNum} | ID: ${s.id} | ${occupied ? '已占用' : '可预约'}`;
        if (!occupied) {
          cell.dataset.seatId  = s.id;
          cell.dataset.seatNum = s.seatNum;
          cell.addEventListener('click', onSeatClick);
        }
      } else if (obstacles.has(key)) {
        cell.classList.add('seat-obstacle');
      } else {
        cell.classList.add('seat-obstacle');
      }
      grid.appendChild(cell);
    }
  }

  $('seat-grid-wrap').innerHTML = '';
  $('seat-grid-wrap').appendChild(grid);
}

function onSeatClick(e) {
  const cell = e.currentTarget;
  const id  = parseInt(cell.dataset.seatId);
  const num = cell.dataset.seatNum;
  const idx = state.selectedSeats.findIndex(s => s.id === id);
  if (idx >= 0) {
    state.selectedSeats.splice(idx, 1);
    cell.classList.replace('seat-selected', 'seat-available');
  } else {
    state.selectedSeats.push({ id, seatNum: num });
    cell.classList.replace('seat-available', 'seat-selected');
  }
  renderSelectedList();
  $('btn-save').disabled = state.selectedSeats.length === 0;
}

function renderSelectedList() {
  const el = $('selected-list');
  if (!state.selectedSeats.length) { el.innerHTML = ''; return; }
  el.innerHTML = '<div style="margin-top:10px;font-size:.875rem;color:#555;margin-bottom:4px">已选座位（按优先级顺序）：</div>' +
    state.selectedSeats.map((s, i) =>
      `<span class="tag">${i+1}. 座位 ${s.seatNum} <span class="rm" data-idx="${i}">✕</span></span>`
    ).join('');
  el.querySelectorAll('.rm').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx);
      const removed = state.selectedSeats.splice(idx, 1)[0];
      // Un-select in grid
      document.querySelectorAll(`[data-seat-id="${removed.id}"]`).forEach(c => {
        c.classList.replace('seat-selected', 'seat-available');
      });
      renderSelectedList();
      $('btn-save').disabled = state.selectedSeats.length === 0;
    });
  });
}

// ---- Step 4: save config ----
$('btn-save').addEventListener('click', async () => {
  $('btn-save').disabled = true;
  setMsg('step4-msg', '保存中…', 'info');

  const payload = {
    seatIds: state.selectedSeats.map(s => s.id),
    deptIdEnc: state.deptIdEnc,
    roomId: state.roomId,
    firstLevel: state.firstLevel,
    secondLevel: state.secondLevel,
    thirdLevel: state.thirdLevel,
    startTime: state.startTime,
    endTime: state.endTime,
    targetDateMode: state.dateMode,
    targetDate: state.targetDate,
  };

  try {
    const resp = await fetch('/api/save-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const json = await resp.json();
    if (json.success) {
      setMsg('step4-msg',
        `🎉 ${json.msg}<br>现在可以关闭此页面，运行 <code>python reserve_once.py</code> 进行预约。`,
        'success');
    } else {
      setMsg('step4-msg', json.msg || '保存失败', 'error');
      $('btn-save').disabled = false;
    }
  } catch(e) {
    setMsg('step4-msg', e.message, 'error');
    $('btn-save').disabled = false;
  }
});
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    host = "127.0.0.1"
    port = 5000
    print("=" * 60)
    print("超星图书馆配置向导")
    print(f"请在浏览器中访问：http://{host}:{port}")
    print("按 Ctrl+C 退出")
    print("=" * 60)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
