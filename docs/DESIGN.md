# kc_modbus_mcp -- Design Document

> **English summary:** MCP Server for Modbus TCP devices. Lets LLM agents read/write PLC registers by name through YAML-based device profiles, because nobody should have to whisper raw hex addresses at an AI. Includes a built-in simulator for testing without real hardware (or friends who own PLCs). This document covers architecture, YAML profile schema, MCP tool definitions, data flow, simulator design, and Docker deployment.

---

# 設計文件

## 概觀

讓 LLM Agent 透過 MCP 協議跟 Modbus TCP 設備好好溝通。使用者用 YAML 定義設備的寄存器映射（device profile），AI agent 用名稱讀寫寄存器 -- 不需要背 raw address，人生已經夠苦了。

我一直在看市面上的 Modbus MCP Server，發現大家有著驚人一致的短板：
1. **無語義化寄存器映射** -- AI 必須知道 raw address（如 40001），你跟它說「讀取溫度」它只會一臉茫然
2. **無資料型別轉換** -- 回傳 raw uint16，float32 大概被認為太奢侈了
3. **無內建模擬器** -- 想測試就要搞硬體，門檻直接拉到天花板
4. **無設備描述檔** -- 無法預先設定連線資訊跟寄存器映射，每次操作都像在重新發明輪子

kc_modbus_mcp 把以上全部修了。是的，我就是那個不嫌事多的人。

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

用 YAML 定義，支援註解。放在 `devices.yaml`。看起來像設定檔，用起來像超能力（好吧，也許只是普通能力，但比背位址好多了）：

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

Modbus 的 function code 就像菜單上的編號，你不用全背，但知道有哪些選項總是好的：

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

給正常人用的工具。這個專案存在的理由。

| Tool | 參數 | 說明 |
|------|------|------|
| `list_devices` | -- | 列出所有已定義的設備 |
| `list_registers` | device | 列出設備所有寄存器及 metadata |
| `read_device` | device, register | 讀取命名寄存器，回傳轉換後的值 + 單位 |
| `write_device` | device, register, value | 寫入命名寄存器 |
| `device_status` | device | 測試連線，回報 online/offline |

### Raw 模式（進階）

給喜歡直接面對寄存器、不需要任何抽象層保護的勇者。我不評判。

| Tool | 參數 | 說明 |
|------|------|------|
| `read_registers` | host, port, slave_id, function_code, address, count | Raw 寄存器讀取 |
| `write_registers` | host, port, slave_id, function_code, address, values | Raw 寄存器寫入 |
| `scan_registers` | host, port, slave_id, start, end | 掃描位址範圍找非零值 |

---

## 資料流

看看你的一句「讀取溫度」在背後經歷了什麼。別說我沒為你負重前行。

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

內建 pymodbus Modbus TCP server，git clone 下來就能自己玩，不需要真實硬體。你的筆電終於有了工廠夢。

### 功能
- 預設 port 5020（避免跟真實設備的 502 打架）
- 預載跟 `devices.yaml` 範例對應的寄存器
- 模擬數據變化：溫度用正弦波假裝自然、濕度靠隨機數搖擺、馬達和幫浦乖乖保持你寫入的值
- 獨立腳本：`python simulator.py`
- 當然也整合在 Docker Compose 裡面

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

提供 OpenClaw agent 的 skill 封裝，因為沒有人想打那麼長的指令：

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

兩個容器，一個指令，零煩惱（大概）：

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

沒有什麼花俏的框架，就是幾個靠譜的工具組在一起：

- Python 3.12+
- FastMCP（MCP SDK）
- pymodbus（async client + server）
- PyYAML
- Docker / Docker Compose
