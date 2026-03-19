# 「讀取工廠溫度」— Modbus MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[English](README.md)

Modbus TCP 設備的 MCP Server。用 YAML 定義設備描述檔，讓 AI Agent 用名稱讀寫 PLC 寄存器 — 不需要知道 raw address。

內建 **Modbus TCP 模擬器**，不需要真實硬體即可完整測試。

---

## 為什麼做這個

目前市面上的 Modbus MCP Server 共通的短板：

1. **無語義化寄存器映射** — AI 必須知道 raw address（如 40001），無法用「讀取溫度」操作
2. **無資料型別轉換** — 回傳 raw uint16，不處理 float32 / int32 等多寄存器型別
3. **無內建模擬器** — 測試需要外部硬體或第三方模擬器
4. **無設備描述檔** — 無法預先設定設備連線資訊與寄存器映射

本專案解決以上全部問題。

---

## 架構

```
使用者（CLI / Chat / OpenClaw）
  → AI Agent（Claude / OpenClaw / etc.）
    → MCP Protocol（Streamable HTTP）
      → kc_modbus_mcp（FastMCP Server）
        → Profile Manager（YAML 設備描述檔）
        → pymodbus（async Modbus TCP client）
      → Modbus TCP 設備 / 內建模擬器
```

## 功能

- **自然語言控制** —「讀取工廠溫度」直接可用
- **YAML 設備描述檔** — 寄存器名稱映射到位址、資料型別、單位、縮放比例
- **8 個 MCP 工具** — 5 個 profile 模式 + 3 個 raw 模式
- **自動資料型別轉換** — float32, int32, uint16, bool，支援 byte order 和 scale
- **內建 Modbus TCP 模擬器** — 正弦波溫度、隨機濕度/壓力、可寫入的線圈
- **Docker 一鍵啟動** — `docker compose up -d` 同時啟動模擬器和 MCP Server
- **OpenClaw Skill** — 本地 LLM agent 的 wrapper script

---

## 展示

![AI agent 讀取 Modbus 設備寄存器](docs/images/demo-snapshot.png)

---

## 快速開始

### 1. 下載安裝

```bash
git clone https://github.com/KerberosClaw/kc_modbus_mcp.git
cd kc_modbus_mcp
uv sync
```

### 2. 啟動模擬器

```bash
uv run python simulator.py
# Modbus TCP 模擬器在 port 5020 執行
```

### 3. 啟動 MCP Server

```bash
# 另開一個終端
uv run python server.py
# MCP Server 在 port 8765 執行，已載入 devices.yaml
```

### 4. 測試

```bash
npm install -g mcporter
mcporter config add modbus --url http://localhost:8765/mcp
mcporter call modbus.list_devices
mcporter call modbus.read_device device=factory_sensor register=temperature
mcporter call modbus.write_device device=factory_sensor register=motor_speed value=1500
mcporter call modbus.device_status device=factory_sensor
```

### 或用 Docker Compose

```bash
docker compose up -d
# 模擬器在 :5020，MCP Server 在 :8765
```

---

## 設備描述檔（YAML）

在 `devices.yaml` 定義你的 Modbus 設備：

```yaml
devices:
  factory_sensor:
    host: 192.168.1.100
    port: 502
    slave_id: 1
    byte_order: big               # big | little | mixed
    registers:
      temperature:
        address: 0
        function_code: 3          # 3=holding, 4=input
        data_type: float32
        scale: 0.1
        unit: "°C"
        access: read
        description: "環境溫度感測器"
      motor_speed:
        address: 4
        function_code: 3
        data_type: uint16
        unit: "RPM"
        access: read_write
        description: "馬達轉速設定值"
      pump_on:
        address: 0
        function_code: 1          # 1=coil
        data_type: bool
        access: read_write
        description: "幫浦開關"
```

### 支援的資料型別

| 型別 | 寄存器數 | 範圍 |
|------|---------|------|
| `bool` | coil (1 bit) | true/false |
| `uint16` | 1 | 0 – 65535 |
| `int16` | 1 | -32768 – 32767 |
| `uint32` | 2 | 0 – 4294967295 |
| `int32` | 2 | -2147483648 – 2147483647 |
| `float32` | 2 | IEEE 754 |

---

## MCP Tools

### Profile 模式（主要）

| Tool | 說明 |
|------|------|
| `list_devices` | 列出所有已配置的設備 |
| `list_registers` | 列出設備所有寄存器及 metadata |
| `read_device` | 讀取命名寄存器 — 回傳轉換後的值 + 單位 |
| `write_device` | 寫入命名寄存器 |
| `device_status` | 檢查設備是否在線 |

### Raw 模式（進階）

| Tool | 說明 |
|------|------|
| `read_registers` | 用 host/port/slave_id/fc/address 直接讀取 |
| `write_registers` | 用 host/port/slave_id/fc/address 直接寫入 |
| `scan_registers` | 掃描位址範圍找非零值 |

---

## 內建模擬器

基於 pymodbus 的 Modbus TCP server，具有動態數據。不需要真實硬體。

| 寄存器 | Address | FC | Type | 行為 |
|--------|---------|-----|------|------|
| temperature | HR 0-1 | 3 | float32 | 正弦波 20~30°C |
| humidity | HR 2-3 | 3 | float32 | 隨機 40~60%RH |
| motor_speed | HR 4 | 3 | uint16 | 保持寫入值 |
| pressure | IR 0 | 4 | uint16 | 隨機 900~1100 kPa |
| pump_on | Coil 0 | 1 | bool | 保持寫入值 |
| valve_open | Coil 1 | 1 | bool | 保持寫入值 |

---

## 專案結構

```
kc_modbus_mcp/
├── server.py               # MCP Server 進入點
├── simulator.py            # 內建 Modbus TCP 模擬器
├── devices.yaml            # 設備描述檔範例
├── src/
│   ├── __init__.py
│   ├── profile.py          # YAML profile 載入 + 寄存器解析
│   ├── client.py           # pymodbus async client 封裝
│   ├── converter.py        # 資料型別轉換（raw ↔ 工程值）
│   └── tools.py            # MCP tool 定義
├── openclaw-skill/
│   ├── SKILL.md            # OpenClaw skill 定義
│   ├── _meta.json
│   └── scripts/
│       └── modbus          # CLI wrapper script
├── tests/                  # 自動化測試
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── DESIGN.md
├── LICENSE
└── .gitignore
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `MODBUS_PROFILE` | `devices.yaml` | 設備描述檔路徑 |
| `MCP_HOST` | `0.0.0.0` | MCP Server 綁定位址 |
| `MCP_PORT` | `8765` | MCP Server 埠號 |
| `SIMULATOR_HOST` | `0.0.0.0` | 模擬器綁定位址 |
| `SIMULATOR_PORT` | `5020` | 模擬器埠號 |

---

## OpenClaw 整合

OpenClaw / 本地 LLM agent 可用 wrapper script 簡化指令：

```bash
modbus list
modbus status factory_sensor
modbus read factory_sensor temperature
modbus write factory_sensor motor_speed 1500
```

### 安裝

```bash
cp -r openclaw-skill ~/.openclaw/workspace/skills/modbus
ln -s $(pwd)/openclaw-skill/scripts/modbus /opt/homebrew/bin/modbus
```

在 `~/.openclaw/workspace/AGENTS.md` 加入：

```markdown
## Modbus 設備控制

需要查詢設備數據時 → 直接執行 `modbus` 指令。

modbus list
modbus status factory_sensor
modbus read factory_sensor temperature
modbus write factory_sensor motor_speed 1500
```

---

## 開發

```bash
# 不用 Docker 執行
uv run python simulator.py &
uv run python server.py

# MCP Inspector（Web UI）
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
```

---

## TODO

- [ ] 多設備連線池
- [ ] Polling 模式 + 可配置快取間隔
- [ ] 變化偵測（值變動時通知）
- [ ] Modbus RTU（Serial）支援
- [ ] Web UI 編輯設備描述檔

---

