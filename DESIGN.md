# kc_modbus_mcp — Design Document

> **English summary:** MCP Server for Modbus TCP devices. Lets LLM agents read/write PLC registers by name through YAML-based device profiles. Includes a built-in simulator for testing without real hardware. This document covers architecture, YAML profile schema, MCP tool definitions, data flow, simulator design, and Docker deployment.

---

# 設計文件

## 概觀

讓 LLM Agent 透過 MCP 協議與 Modbus TCP 設備互動。使用者用 YAML 定義設備的寄存器映射（device profile），AI agent 用名稱讀寫寄存器，不需要知道 raw address。

目前市面上的 Modbus MCP Server 共通的短板：
1. **無語義化寄存器映射** — AI 必須知道 raw address（如 40001），無法用「讀取溫度」操作
2. **無資料型別轉換** — 回傳 raw uint16，不處理 float32 / int32 等多寄存器型別
3. **無內建模擬器** — 測試需要外部硬體或第三方模擬器
4. **無設備描述檔** — 無法預先設定設備連線資訊與寄存器映射

kc_modbus_mcp 解決以上全部問題。

---

## 架構

```
LLM（Claude / OpenClaw / etc.）
  → MCP Protocol（stdio）
  → kc_modbus_mcp（FastMCP Server）
    → Profile Mgr（YAML 設備描述檔）
    → pymodbus（async Modbus TCP client）
  → Modbus TCP 設備 / 內建模擬器
```

---

## 設備描述檔（Device Profile）

以 YAML 定義，支援註解。放在 `devices.yaml`：

```yaml
devices:
  factory_sensor:
    host: 192.168.1.100
    port: 502
    slave_id: 1
    byte_order: big            # big | little | mixed
    registers:
      temperature:
        address: 0
        function_code: 3       # 3=holding, 4=input
        data_type: float32     # uint16, int16, uint32, int32, float32, bool
        scale: 0.1
        unit: "°C"
        access: read
        description: "環境溫度感測器"
      motor_speed:
        address: 2
        function_code: 3
        data_type: uint16
        unit: "RPM"
        access: read_write
        description: "馬達轉速設定值"
      pump_on:
        address: 0
        function_code: 1       # 1=coil
        data_type: bool
        access: read_write
        description: "幫浦開關"
```

### 支援的資料型別

| data_type | 寄存器數 | 說明 |
|-----------|---------|------|
| bool | coil / 1 bit | 開/關 |
| uint16 | 1 | 0 ~ 65535 |
| int16 | 1 | -32768 ~ 32767 |
| uint32 | 2 | 0 ~ 4294967295 |
| int32 | 2 | -2147483648 ~ 2147483647 |
| float32 | 2 | IEEE 754 |

### 支援的 Function Code

| Code | 名稱 | 存取 |
|------|------|------|
| 1 | Read Coils | 讀 |
| 2 | Read Discrete Inputs | 讀 |
| 3 | Read Holding Registers | 讀/寫 |
| 4 | Read Input Registers | 讀 |
| 5 | Write Single Coil | 寫 |
| 6 | Write Single Register | 寫 |
| 15 | Write Multiple Coils | 寫 |
| 16 | Write Multiple Registers | 寫 |

---

## MCP Tools

### Profile 模式（主要）

| Tool | 參數 | 說明 |
|------|------|------|
| `list_devices` | — | 列出所有已定義的設備 |
| `list_registers` | device | 列出設備所有寄存器及 metadata |
| `read_device` | device, register | 讀取命名寄存器，回傳轉換後的值 + 單位 |
| `write_device` | device, register, value | 寫入命名寄存器 |
| `device_status` | device | 測試連線，回報 online/offline |

### Raw 模式（進階）

| Tool | 參數 | 說明 |
|------|------|------|
| `read_registers` | host, port, slave_id, function_code, address, count | Raw 寄存器讀取 |
| `write_registers` | host, port, slave_id, function_code, address, values | Raw 寄存器寫入 |
| `scan_registers` | host, port, slave_id, start, end | 掃描位址範圍找非零值 |

---

## 資料流

### 讀取（Profile 模式）

```
LLM: read_device("factory_sensor", "temperature")
  → Profile Mgr 查詢：host=192.168.1.100, port=502, slave_id=1,
    address=0, fc=3, type=float32, scale=0.1
  → pymodbus: read_holding_registers(address=0, count=2, slave=1)
  → raw: [0x4248, 0x0000]
  → float32 轉換: 50.0
  → scale: × 0.1 → 5.0
  → 回傳: { "device": "factory_sensor", "register": "temperature",
            "value": 5.0, "unit": "°C" }
```

### 寫入（Profile 模式）

```
LLM: write_device("factory_sensor", "motor_speed", 1500)
  → Profile Mgr 查詢，確認 access == read_write
  → pymodbus: write_register(address=2, value=1500, slave=1)
  → 回傳: { "device": "factory_sensor", "register": "motor_speed",
            "written": 1500, "unit": "RPM" }
```

---

## 模擬器

內建 pymodbus Modbus TCP server，git clone 後即可自測，不需要真實硬體。

### 功能
- 預設 port 5020（避免與真實設備 502 衝突）
- 預載與 `devices.yaml` 範例對應的寄存器
- 模擬數據變化：溫度正弦波、濕度隨機波動、馬達/幫浦保持寫入值
- 獨立腳本：`python simulator.py`
- 整合在 Docker Compose 中

### 模擬寄存器表

| 寄存器 | Address | FC | Type | 行為 |
|--------|---------|-----|------|------|
| temperature | HR 0-1 | 3 | float32 | 正弦波 20~30°C |
| humidity | HR 2-3 | 3 | float32 | 隨機 40~60% |
| motor_speed | HR 4 | 3 | uint16 | 保持寫入值 |
| pressure | IR 0 | 4 | uint16 | 隨機 900~1100 |
| pump_on | Coil 0 | 1 | bool | 保持寫入值 |
| valve_open | Coil 1 | 1 | bool | 保持寫入值 |

---

## OpenClaw Skill Wrapper

提供 OpenClaw agent 的 skill 封裝，簡化 LLM 指令：

```
modbus list                         → list_devices
modbus status <device>              → device_status
modbus read <device> <register>     → read_device
modbus write <device> <reg> <val>   → write_device
```

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
├── README.md               # 英文
├── README_zh.md            # 中文
├── DESIGN.md               # 本文件
├── LICENSE
└── .gitignore
```

---

## Docker Compose

```yaml
services:
  simulator:
    build: .
    command: python simulator.py
    ports:
      - "5020:5020"

  mcp-server:
    build: .
    command: python server.py
    environment:
      - MODBUS_PROFILE=devices.yaml
    depends_on:
      - simulator
    volumes:
      - ./devices.yaml:/app/devices.yaml
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/KerberosClaw/kc_modbus_mcp.git
cd kc_modbus_mcp

# 2. 啟動模擬器 + MCP Server
docker compose up -d

# 3. 用 MCP client 測試
mcporter connect localhost:8765
> list_devices
> read_device factory_sensor temperature
> write_device factory_sensor motor_speed 1500

# 4. 或本地執行
pip install -e .
python simulator.py &
python server.py
```

---

## 技術棧

- Python 3.12+
- FastMCP（MCP SDK）
- pymodbus（async client + server）
- PyYAML
- Docker / Docker Compose
