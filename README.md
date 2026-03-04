# newpreserve

超星图书馆座位自动预约工具，支持通过本地可视化向导生成配置，无需手动抓包。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置认证 Cookie

```bash
cp .env.example .env
# 在 .env 中填入从浏览器 DevTools 复制的 Cookie
```

### 3a. 使用可视化向导生成配置（推荐）

```bash
python config_wizard.py
```

然后在浏览器访问 **http://127.0.0.1:5000**，按页面提示操作：

> ⚠️ 注意：该服务仅监听本机 `127.0.0.1`，请勿将其暴露到外部网络，因为其中包含您的认证 Cookie。

1. 输入 Cookie 和 `deptIdEnc`（学校加密标识）
2. 选择校区、楼层、阅览室
3. 设置预约日期和时间段
4. 在座位布局图上点选目标座位（可多选，按优先级排列）
5. 点击「保存配置」，自动写入 `config/config.yml`

### 3b. 手动编辑配置

参考 `config/config.yml` 直接填写座位 ID、时间段等参数。

### 4. 运行预约脚本

```bash
python reserve_once.py
```

### 5. 定时调度（可选）

使用系统 cron 在每天 19:59 自动执行（预约次日座位）：

```cron
59 19 * * * cd /path/to/newpreserve && python reserve_once.py
```

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `reserve_once.py` | 预约脚本，每次执行一轮预约尝试 |
| `config_wizard.py` | 本地 Web 配置向导，辅助生成 `config/config.yml` |
| `config/config.yml` | 非敏感配置（座位 ID、时间段等） |
| `.env` | 敏感信息（Cookie），不提交到仓库 |
| `.env.example` | `.env` 模板 |