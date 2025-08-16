#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
藍牙設備掃描測試腳本
用於測試和驗證藍牙設備掃描功能
"""

import asyncio
import sys
import os

# 添加當前目錄到Python路徑
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from bleak import BleakScanner
    print("✅ bleak 庫已導入")
except ImportError:
    print("❌ 請先安裝 bleak: pip install bleak")
    sys.exit(1)

async def scan_devices():
    """掃描BLE設備"""
    print("🔍 正在掃描BLE設備...")
    print("請確保您的ESP32設備已開啟並在廣播")
    print("-" * 50)
    
    try:
        # 掃描設備，超時10秒
        devices = await BleakScanner.discover(timeout=10.0)
        
        if not devices:
            print("❌ 未發現任何BLE設備")
            print("\n可能的原因:")
            print("1. 沒有BLE設備在廣播")
            print("2. 藍牙功能未開啟")
            print("3. 權限不足")
            print("4. ESP32設備未正確配置BLE")
            return None
        
        print(f"📱 發現 {len(devices)} 個BLE設備:")
        print("-" * 50)
        
        esp32_devices = []
        
        for i, device in enumerate(devices):
            name = device.name or "Unknown"
            device_type = "其他"
            
            # 識別ESP32設備
            if name and ("ESP32" in name.upper() or "VOICE" in name.upper() or "MIC" in name.upper()):
                device_type = "ESP32設備"
                esp32_devices.append(i)
                
            print(f"  {i+1:2d}. {name:20s} ({device.address}) - {device_type}")
            
            # 顯示額外信息
            if device.rssi:
                print(f"       RSSI: {device.rssi} dBm")
            if device.metadata:
                print(f"       元數據: {device.metadata}")
        
        print("-" * 50)
        
        if esp32_devices:
            print(f"💡 建議選擇: {', '.join([str(i+1) for i in esp32_devices])} (ESP32設備)")
        else:
            print("⚠️ 未找到ESP32設備")
            print("請確認:")
            print("1. ESP32設備已開啟")
            print("2. ESP32程式已上傳並運行")
            print("3. ESP32正在廣播BLE服務")
        
        return devices
        
    except Exception as e:
        print(f"❌ 設備掃描錯誤: {e}")
        print("\n可能的解決方案:")
        print("1. 檢查藍牙是否開啟")
        print("2. 檢查系統權限")
        print("3. 重新啟動藍牙服務")
        return None

def main():
    """主函數"""
    print("🎤 ESP32藍牙設備掃描測試")
    print("=" * 50)
    
    # 檢查系統信息
    print("系統信息:")
    print(f"  Python版本: {sys.version}")
    print(f"  作業系統: {sys.platform}")
    
    # 運行掃描
    devices = asyncio.run(scan_devices())
    
    if devices:
        print(f"\n✅ 掃描完成，找到 {len(devices)} 個設備")
        
        # 讓用戶選擇設備進行測試
        while True:
            try:
                choice = input(f"\n請選擇要測試的設備 [1-{len(devices)}] 或按 Enter 退出: ").strip()
                
                if not choice:
                    print("👋 退出測試")
                    break
                
                index = int(choice) - 1
                if 0 <= index < len(devices):
                    selected_device = devices[index]
                    print(f"\n🔍 測試設備: {selected_device.name}")
                    print(f"   地址: {selected_device.address}")
                    print(f"   RSSI: {selected_device.rssi} dBm")
                    
                    # 這裡可以添加連接測試
                    print("   注意: 連接測試需要完整的BLE處理程式")
                    break
                else:
                    print(f"❌ 請輸入 1-{len(devices)} 之間的數字")
                    
            except ValueError:
                print("❌ 請輸入有效的數字")
            except KeyboardInterrupt:
                print("\n👋 用戶中斷")
                break
    
    print("\n🎯 測試完成")

if __name__ == "__main__":
    main()
