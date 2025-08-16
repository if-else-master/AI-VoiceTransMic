#!/usr/bin/env python3
"""
ESP32 AI語音翻譯麥克風系統 - 主啟動程序

功能特性:
- ESP32 BLE連接，穩定不斷線
- INMP441高品質音頻捕獲 (16kHz/16bit)
- I2C LCD即時翻譯逐字稿顯示
- DAC音頻回放，直接驅動喇叭
- GPIO2按鈕控制AI即時語音克隆翻譯
- XTTS-v2語音克隆技術
- 邊聽邊翻譯邊播放的即時處理

使用方法:
1. 上傳 esp32_voice_mic/esp32_voice_mic.ino 到ESP32
2. 運行此程序: python run_voice_translator.py
3. 按照提示配置API密鑰和語言設置
4. 連接ESP32設備
5. 按下GPIO2按鈕開始語音翻譯

作者: AI Assistant
版本: 3.0 (完整版)
日期: 2024
"""

import sys
import os
import time
import subprocess

def check_dependencies():
    """檢查必要的依賴包"""
    print("🔍 檢查系統依賴...")
    
    required_packages = [
        'bleak',
        'google-generativeai', 
        'torch',
        'numpy',
        'scipy',
        'wave',
        'pyaudio'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == 'google-generativeai':
                import google.generativeai
            else:
                __import__(package.replace('-', '_'))
            print(f"✅ {package}")
        except ImportError:
            missing_packages.append(package)
            print(f"❌ {package} - 缺失")
    
    if missing_packages:
        print(f"\n⚠️ 缺少依賴包: {', '.join(missing_packages)}")
        print("請運行以下命令安裝:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ 所有依賴包已安裝")
    return True

def check_xtts_model():
    """檢查XTTS-v2模型"""
    print("\n🤖 檢查XTTS-v2模型...")
    
    xtts_path = "XTTS-v2"
    required_files = [
        "config.json",
        "model.pth", 
        "dvae.pth",
        "mel_stats.pth",
        "speakers_xtts.pth",
        "vocab.json"
    ]
    
    if not os.path.exists(xtts_path):
        print(f"❌ XTTS-v2模型目錄不存在: {xtts_path}")
        return False
    
    missing_files = []
    for file in required_files:
        file_path = os.path.join(xtts_path, file)
        if os.path.exists(file_path):
            print(f"✅ {file}")
        else:
            missing_files.append(file)
            print(f"❌ {file} - 缺失")
    
    if missing_files:
        print(f"\n⚠️ 缺少XTTS-v2模型文件: {', '.join(missing_files)}")
        print("請確保XTTS-v2模型文件完整")
        return False
    
    print("✅ XTTS-v2模型文件完整")
    return True

def check_esp32_code():
    """檢查ESP32代碼"""
    print("\n🔧 檢查ESP32代碼...")
    
    esp32_file = "esp32_voice_mic/esp32_voice_mic.ino"
    if os.path.exists(esp32_file):
        print(f"✅ ESP32代碼文件存在: {esp32_file}")
        
        # 檢查代碼中的關鍵功能
        with open(esp32_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        features = [
            ("BLE功能", "BluetoothSerial"),
            ("I2S音頻", "driver/i2s.h"),
            ("DAC輸出", "driver/dac.h"),
            ("LCD顯示", "LiquidCrystal_I2C.h"),
            ("音頻播放", "playAudio"),
            ("語音檢測", "checkVoiceActivity"),
            ("按鈕控制", "checkButtons")
        ]
        
        for feature_name, keyword in features:
            if keyword in content:
                print(f"✅ {feature_name}")
            else:
                print(f"❌ {feature_name} - 可能缺失")
        
        return True
    else:
        print(f"❌ ESP32代碼文件不存在: {esp32_file}")
        print("請確保ESP32代碼文件位於正確位置")
        return False

def main():
    """主程序"""
    print("🎤 ESP32 AI語音翻譯麥克風系統 v3.0")
    print("=" * 60)
    print("功能特性:")
    print("✨ ESP32 BLE穩定連接")
    print("🎤 INMP441高品質音頻捕獲 (16kHz/16bit)")  
    print("📺 I2C LCD即時翻譯逐字稿顯示")
    print("🔊 DAC音頻回放，直接驅動喇叭")
    print("🎛️ GPIO2按鈕控制AI語音克隆翻譯")
    print("🤖 XTTS-v2語音克隆技術")
    print("⚡ 邊聽邊翻譯邊播放的即時處理")
    print("=" * 60)
    
    # 系統檢查
    print("\n🔍 執行系統檢查...")
    
    checks = [
        ("Python依賴包", check_dependencies),
        ("XTTS-v2模型", check_xtts_model),
        ("ESP32代碼", check_esp32_code)
    ]
    
    all_passed = True
    for check_name, check_func in checks:
        if not check_func():
            all_passed = False
    
    if not all_passed:
        print("\n❌ 系統檢查失敗，請修復上述問題後重新運行")
        return
    
    print("\n✅ 系統檢查通過！")
    
    # 啟動主程序
    print("\n🚀 啟動AI語音翻譯系統...")
    print("\n" + "=" * 60)
    print("使用說明:")
    print("1. 確保ESP32已燒錄最新代碼並開機")
    print("2. 按照提示配置Gemini API密鑰")
    print("3. 選擇源語言和目標語言")
    print("4. 選擇語音克隆文件（可選）")
    print("5. 掃描並連接ESP32設備")
    print("6. 按下ESP32的GPIO2按鈕開始語音翻譯")
    print("7. 系統將自動進行: 錄音 → 轉錄 → 翻譯 → 語音合成 → 播放")
    print("=" * 60)
    
    # 等待用戶確認
    input("\n按Enter開始啟動系統...")
    
    try:
        # 導入並啟動主系統
        from bluetooth_voice_handler import ESP32VoiceMicrophoneApp
        
        app = ESP32VoiceMicrophoneApp()
        app.run()
        
    except KeyboardInterrupt:
        print("\n👋 用戶中斷程序")
    except ImportError as e:
        print(f"\n❌ 導入錯誤: {e}")
        print("請確保所有必要的Python文件都在當前目錄")
    except Exception as e:
        print(f"\n❌ 運行錯誤: {e}")
    finally:
        print("\n🔄 系統已關閉")

if __name__ == "__main__":
    main()
