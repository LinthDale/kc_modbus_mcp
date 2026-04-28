"""
kc_mcp_modbus — Built-in Modbus TCP Simulator
內建 Modbus TCP 模擬器，不需要真實硬體即可測試 MCP Server。
"""

import asyncio
import math
import random
import struct
import time
import os
import logging

from pymodbus.datastore import (
    ModbusServerContext,
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("simulator")

# --- 設定 ---
HOST = os.getenv("SIMULATOR_HOST", "0.0.0.0")
PORT = int(os.getenv("SIMULATOR_PORT", "5020"))
UPDATE_INTERVAL = 2  # 秒


def float32_to_registers(value: float) -> list[int]:
    """將 float32 轉換為 2 個 16-bit registers (big-endian)"""
    packed = struct.pack(">f", value)
    high = int.from_bytes(packed[0:2], "big")
    low = int.from_bytes(packed[2:4], "big")
    return [high, low]


def build_datastore() -> ModbusDeviceContext:
    """建立初始寄存器資料"""
    # Holding Registers (FC 3): address 0-4
    #   0-1: temperature (float32) = 25.0
    #   2-3: humidity (float32) = 50.0
    #   4:   motor_speed (uint16) = 0
    hr_values = float32_to_registers(25.0) + float32_to_registers(50.0) + [0] + [0] * 10

    # Input Registers (FC 4): address 0
    #   0: pressure (uint16) = 1000
    # pymodbus 3.12: ModbusSequentialDataBlock 需要足夠的 padding
    ir_values = [1000] + [0] * 9

    # Coils (FC 1): address 0-1
    #   0: pump_on = False
    #   1: valve_open = False
    coil_values = [False, False] + [False] * 8

    # Discrete Inputs (FC 2): 預留
    di_values = [False] * 10

    return ModbusDeviceContext(
        di=ModbusSequentialDataBlock(1, di_values),
        co=ModbusSequentialDataBlock(1, coil_values),
        hr=ModbusSequentialDataBlock(1, hr_values),
        ir=ModbusSequentialDataBlock(1, ir_values),
    )


async def update_simulated_data(context: ModbusServerContext):
    """定時更新模擬數據"""
    slave_id = 1
    start_time = time.time()

    while True:
        await asyncio.sleep(UPDATE_INTERVAL)
        elapsed = time.time() - start_time
        store = context[slave_id]

        # 溫度：正弦波 20~30°C
        temp = 25.0 + 5.0 * math.sin(elapsed * 0.1)
        temp_regs = float32_to_registers(temp)
        store.setValues(3, 0, temp_regs)  # FC 3 = holding registers

        # 濕度：隨機波動 40~60%
        humidity = 50.0 + 10.0 * math.sin(elapsed * 0.07) + random.uniform(-2, 2)
        humidity = max(0.0, min(100.0, humidity))
        hum_regs = float32_to_registers(humidity)
        store.setValues(3, 2, hum_regs)

        # 壓力：隨機 900~1100 kPa
        pressure = 1000 + int(100 * math.sin(elapsed * 0.05) + random.randint(-20, 20))
        pressure = max(0, min(65535, pressure))
        store.setValues(4, 0, [pressure])  # FC 4 = input registers

        log.info(
            f"Updated: temp={temp:.1f}°C, humidity={humidity:.1f}%RH, "
            f"pressure={pressure}kPa"
        )


async def run_server():
    """啟動 Modbus TCP 模擬器"""
    store = build_datastore()
    context = ModbusServerContext(devices={1: store}, single=False)

    log.info(f"Starting Modbus TCP Simulator on {HOST}:{PORT}")
    log.info("Register map:")
    log.info("  HR 0-1: temperature (float32, °C) — sine wave 20~30")
    log.info("  HR 2-3: humidity (float32, %RH) — random 40~60")
    log.info("  HR 4:   motor_speed (uint16, RPM) — holds written value")
    log.info("  IR 0:   pressure (uint16, kPa) — random 900~1100")
    log.info("  Coil 0: pump_on (bool) — holds written value")
    log.info("  Coil 1: valve_open (bool) — holds written value")

    # 啟動背景更新任務
    updater = asyncio.create_task(update_simulated_data(context))

    try:
        await StartAsyncTcpServer(
            context=context,
            address=(HOST, PORT),
        )
    finally:
        updater.cancel()


if __name__ == "__main__":
    asyncio.run(run_server())
