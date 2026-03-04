#!/usr/bin/env python3
"""
超星图书馆座位自动预约脚本 v1

使用方法：
    python reserve_once.py

前置准备：
    1. pip install -r requirements.txt
    2. cp .env.example .env  # 填入从浏览器拷贝的 Cookie
    3. 编辑 config/config.yml，填入座位 ID、时间段等参数

定时调度示例（Linux cron，每天 19:59 执行，预约明天的座位）：
    59 19 * * * cd /path/to/newpreserve && python reserve_once.py

注意事项：
    - 本脚本仅执行一次预约尝试，定时调度由操作系统负责
    - 不实现自动登录、自动签到、自动退座等功能
    - Cookie 失效时请重新从浏览器获取并更新 .env
"""

import os
import sys
import time
import logging
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

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent

# 超星图书馆预约系统 API 地址
API_BASE = "https://office.chaoxing.com"
SUBMIT_URL = f"{API_BASE}/data/apps/seat/submit"

# HTTP 请求超时时间（秒）
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """加载 config/config.yml，返回配置字典。"""
    config_path = BASE_DIR / "config" / "config.yml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在：{config_path}\n"
            "请参考 config/config.yml 模板创建配置文件。"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if cfg is None:
        raise ValueError("config/config.yml 内容为空，请检查配置文件。")
    return cfg


def load_env() -> dict:
    """加载 .env 中的敏感信息，返回包含 cookie 的字典。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        raise FileNotFoundError(
            ".env 文件不存在。\n"
            "请复制 .env.example 为 .env，并填入从浏览器获取的 Cookie。"
        )
    load_dotenv(env_path, override=True)
    cookie = os.getenv("CX_COOKIE", "").strip().strip('"').strip("'")
    if not cookie or cookie.startswith("UID=xxx"):
        raise ValueError(
            "CX_COOKIE 未设置或仍为示例值。\n"
            "请在 .env 文件中填入真实的 Cookie 字符串。"
        )
    return {"cookie": cookie}


# ---------------------------------------------------------------------------
# 日期与时间戳计算
# ---------------------------------------------------------------------------

def get_target_date(config: dict) -> str:
    """根据配置计算目标预约日期，返回 'YYYY-MM-DD' 字符串。"""
    mode = config.get("target_date_mode", "tomorrow")
    if mode == "tomorrow":
        return (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    elif mode == "date":
        target = config.get("target_date")
        if not target:
            raise ValueError(
                "target_date_mode 为 'date' 时，必须在 config.yml 中设置 target_date"
            )
        # 验证日期格式
        datetime.datetime.strptime(str(target), "%Y-%m-%d")
        return str(target)
    else:
        raise ValueError(
            f"未知的 target_date_mode：'{mode}'，可选值为 'tomorrow' 或 'date'"
        )


def date_time_to_ms(date_str: str, time_str: str) -> int:
    """
    将日期字符串和时间字符串组合，转换为北京时间（CST/UTC+8）的 Unix 毫秒时间戳。

    Args:
        date_str: 格式 'YYYY-MM-DD'
        time_str: 格式 'HH:MM'

    Returns:
        Unix 时间戳（毫秒）
    """
    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    tz_cst = datetime.timezone(datetime.timedelta(hours=8))
    dt_cst = dt.replace(tzinfo=tz_cst)
    return int(dt_cst.timestamp() * 1000)


# ---------------------------------------------------------------------------
# 预约请求
# ---------------------------------------------------------------------------

def reserve_seat(
    session: requests.Session,
    seat_id: int,
    start_ms: int,
    end_ms: int,
    dept_id_enc: str,
) -> tuple:
    """
    发送一次预约请求。

    接口说明（基于抓包数据 2026-03-04-231350/office.chaoxing.com/data/apps/seat/submit）：
      URL:    https://office.chaoxing.com/data/apps/seat/submit
      Method: GET（与其他 API 端点保持一致，采用查询参数传参）
      参数：
        seatId      - 座位的数据库 ID（整数），来自 seatgrid 接口 seatDatas[].id
        startTime   - 预约开始时间（Unix 毫秒时间戳，北京时间 UTC+8）
        endTime     - 预约结束时间（Unix 毫秒时间戳，北京时间 UTC+8）
        deptIdEnc   - 学校的加密标识，来自页面 JS 变量 deptIdEnc / fidEnc
      认证：
        Cookie 请求头（从浏览器获取，存放于 .env 的 CX_COOKIE 中）

    Args:
        session:     已配置 Cookie 等请求头的 requests.Session
        seat_id:     座位 ID（整数）
        start_ms:    预约开始时间（Unix 毫秒）
        end_ms:      预约结束时间（Unix 毫秒）
        dept_id_enc: 学校加密标识

    Returns:
        (success: bool, message: str)
    """
    params = {
        "seatId": seat_id,
        "startTime": start_ms,
        "endTime": end_ms,
        "deptIdEnc": dept_id_enc,
    }

    try:
        resp = session.get(SUBMIT_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return False, "请求超时，请检查网络连接"
    except requests.exceptions.ConnectionError as e:
        return False, f"网络连接错误：{e}"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP 错误：{e}"
    except requests.exceptions.RequestException as e:
        return False, f"请求异常：{e}"

    # 检查是否被重定向到登录页（返回 HTML 而非 JSON）
    content_type = resp.headers.get("Content-Type", "")
    response_text = resp.text.strip()
    if "text/html" in content_type or response_text.startswith("<!DOCTYPE"):
        return False, "登录态失效，请重新在浏览器登录后更新 .env 中的 CX_COOKIE"

    try:
        data = resp.json()
    except ValueError:
        return False, f"响应格式错误（非 JSON），内容前 200 字符：{response_text[:200]}"

    if data.get("success"):
        seat_reserve = data.get("data", {}).get("seatReserve", {})
        seat_num = seat_reserve.get("seatNum", "?")
        room_first = seat_reserve.get("firstLevelName", "")
        room_second = seat_reserve.get("secondLevelName", "")
        room_third = seat_reserve.get("thirdLevelName", "")
        location = " - ".join(filter(None, [room_first, room_second, room_third]))
        return True, f"预约成功！座位号: {seat_num}，位置: {location}"
    else:
        msg = (
            data.get("msg")
            or data.get("message")
            or data.get("info")
            or str(data)
        )
        # 对常见错误给出更友好的提示
        if any(kw in msg for kw in ("登录", "login", "session", "auth", "token")):
            return False, f"登录态失效，请重新在浏览器登录后更新 .env 中的 CX_COOKIE（原始信息：{msg}）"
        return False, msg


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def setup_logging(config: dict) -> logging.Logger:
    """根据配置初始化日志。"""
    log_cfg = config.get("logging", {})
    level_name = str(log_cfg.get("level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)
    log_file = log_cfg.get("file", "")

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file_path = BASE_DIR / log_file
        handlers.append(
            logging.FileHandler(log_file_path, encoding="utf-8")
        )

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger(__name__)


def main() -> None:
    # 1. 加载配置和敏感信息
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] 配置加载失败：{e}")
        sys.exit(1)

    log = setup_logging(config)

    try:
        env = load_env()
    except (FileNotFoundError, ValueError) as e:
        log.error("敏感信息加载失败：%s", e)
        sys.exit(1)

    log.info("=== 超星图书馆自动预约脚本 v1 ===")

    # 2. 计算目标日期和时间段
    try:
        target_date = get_target_date(config)
    except (ValueError, KeyError) as e:
        log.error("目标日期计算失败：%s", e)
        sys.exit(1)

    time_range = config.get("time_range", {})
    start_time_str = str(time_range.get("start", "08:00"))
    end_time_str = str(time_range.get("end", "22:30"))

    try:
        start_ms = date_time_to_ms(target_date, start_time_str)
        end_ms = date_time_to_ms(target_date, end_time_str)
    except ValueError as e:
        log.error("时间参数格式错误：%s", e)
        sys.exit(1)

    log.info("目标日期：%s", target_date)
    log.info("预约时间段：%s - %s", start_time_str, end_time_str)

    # 3. 读取座位列表和区域参数
    seat_ids = config.get("seat_ids", [])
    area_cfg = config.get("area", {})
    dept_id_enc = str(area_cfg.get("dept_id_enc", ""))

    behavior = config.get("behavior", {})
    max_seats = int(behavior.get("max_seats_to_try", 5))
    interval = float(behavior.get("interval_seconds_between_seats", 0.2))

    if not seat_ids:
        log.error("未配置座位列表，请在 config/config.yml 中设置 seat_ids")
        sys.exit(1)

    if not dept_id_enc:
        log.warning(
            "未配置 area.dept_id_enc，预约请求可能失败。"
            "请从抓包数据中提取 deptIdEnc 并填入 config/config.yml"
        )

    seats_to_try = seat_ids[:max_seats]
    log.info("座位列表（共 %d 个，最多尝试 %d 个）：%s", len(seat_ids), max_seats, seats_to_try)

    # 4. 构建 HTTP Session
    session = requests.Session()
    session.headers.update(
        {
            "Cookie": env["cookie"],
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

    # 5. 依次尝试预约
    success = False
    tried = 0

    for seat_id in seats_to_try:
        tried += 1
        log.info(
            "[%d/%d] 尝试预约座位 ID：%s ...",
            tried,
            len(seats_to_try),
            seat_id,
        )

        ok, msg = reserve_seat(session, seat_id, start_ms, end_ms, dept_id_enc)

        if ok:
            log.info("✓ %s（座位 ID：%s）", msg, seat_id)
            success = True
            break

        # 登录态失效：不重试，直接退出
        if "登录态失效" in msg:
            log.error("✗ %s", msg)
            log.error(
                "请重新在浏览器登录超星图书馆（office.chaoxing.com），"
                "然后从 DevTools 中复制 Cookie 并更新 .env 文件中的 CX_COOKIE。"
            )
            sys.exit(1)

        log.warning("✗ 座位 %s 预约失败：%s", seat_id, msg)

        if tried < len(seats_to_try):
            log.debug("等待 %.1f 秒后尝试下一个座位 ...", interval)
            time.sleep(interval)

    # 6. 输出最终结果
    if success:
        log.info("=== 预约成功，本次共尝试 %d 个座位 ===", tried)
    else:
        log.error("=== 所有座位预约失败，共尝试 %d 个座位 ===", tried)
        log.error(
            "请检查：\n"
            "  1. config/config.yml 中的 seat_ids、dept_id_enc 是否正确\n"
            "  2. .env 中的 CX_COOKIE 是否仍然有效\n"
            "  3. 当前时间是否已到预约开放时间（前一天 20:00）\n"
            "  4. 是否已存在未完成的预约（每人同一时段只能预约一个座位）"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
