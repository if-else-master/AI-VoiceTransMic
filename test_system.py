#!/usr/bin/env python3
"""
ESP32 AI語音翻譯系統 - 快速測試腳本

此腳本用於測試系統各個組件是否正常工作
"""

import sys
import os
import time

def test_imports():
    """測試Python庫導入"""
    print("🔍 測試Python庫導入...")
    
    try:
        import bleak
        print("✅ bleak - BLE通信庫")
    except ImportError:
        print("❌ bleak - 請運行: pip install bleak")
        return False
    
    try:
        import google.generativeai as genai
        print("✅ google-generativeai - Gemini API")
    except ImportError:
        print("❌ google-generativeai - 請運行: pip install google-generativeai")
        return False
    
    try:
        import torch
        print("✅ torch - PyTorch")
    except ImportError:
        print("❌ torch - 請運行: pip install torch")
        return False
    
    try:
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts
        print("✅ TTS - XTTS語音合成")
    except ImportError:
        print("❌ TTS - 請運行: pip install TTS")
        return False
    
    try:
        import numpy as np
        import scipy
        import wave
        print("✅ numpy, scipy, wave - 音頻處理")
    except ImportError:
        print("❌ 音頻處理庫缺失")
        return False
    
    return True

def test_xtts_model():
    """測試XTTS模型文件"""
    print("\n🤖 測試XTTS-v2模型...")
    
    model_path = "XTTS-v2"
    if not os.path.exists(model_path):
        print(f"❌ XTTS-v2目錄不存在: {model_path}")
        return False
    
    required_files = [
        "config.json",
        "model.pth", 
        "dvae.pth",
        "mel_stats.pth",
        "speakers_xtts.pth",
        "vocab.json"
    ]
    
    for file in required_files:
        file_path = os.path.join(model_path, file)
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            print(f"✅ {file} ({size:,} bytes)")
        else:
            print(f"❌ {file} - 文件缺失")
            return False
    
    return True

def test_voice_files():
    """測試語音克隆文件"""
    print("\n🎭 測試語音克隆文件...")
    
    voice_dir = "cloned_voices"
    if not os.path.exists(voice_dir):
        print(f"⚠️ 語音克隆目錄不存在: {voice_dir}")
        print("系統將使用默認語音")
        return True
    
    wav_files = [f for f in os.listdir(voice_dir) if f.endswith('.wav')]
    if wav_files:
        for file in wav_files:
            file_path = os.path.join(voice_dir, file)
            size = os.path.getsize(file_path)
            print(f"✅ {file} ({size:,} bytes)")
        return True
    else:
        print("⚠️ 沒有找到語音克隆文件")
        print("系統將使用默認語音")
        return True

def test_main_modules():
    """測試主要模塊"""
    print("\n📦 測試主要模塊...")
    
    try:
        from main import RealTimeVoiceTranslationSystem
        print("✅ main.py - 語音翻譯系統")
    except ImportError as e:
        print(f"❌ main.py - 導入失敗: {e}")
        return False
    
    try:
        from bluetooth_voice_handler import ESP32BluetoothHandler, ESP32VoiceMicrophoneApp
        print("✅ bluetooth_voice_handler.py - BLE處理器")
    except ImportError as e:
        print(f"❌ bluetooth_voice_handler.py - 導入失敗: {e}")
        return False
    
    return True

def test_xtts_initialization():
    """測試XTTS模型初始化"""
    print("\n🚀 測試XTTS模型初始化...")
    
    try:
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts
        
        print("⏳ 載入配置文件...")
        config = XttsConfig()
        config.load_json("XTTS-v2/config.json")
        print("✅ 配置文件載入成功")
        
        print("⏳ 初始化XTTS模型...")
        model = Xtts.init_from_config(config)
        print("✅ XTTS模型初始化成功")
        
        print("⏳ 載入模型權重...")
        model.load_checkpoint(config, checkpoint_dir="XTTS-v2/", eval=True)
        print("✅ 模型權重載入成功")
        
        print("✅ XTTS模型完全可用！")
        return True
        
    except Exception as e:
        print(f"❌ XTTS模型初始化失敗: {e}")
        return False

def test_translation_system():
    """測試翻譯系統"""
    print("\n🌍 測試翻譯系統初始化...")
    
    try:
        from main import RealTimeVoiceTranslationSystem
        
        print("⏳ 初始化翻譯系統...")
        system = RealTimeVoiceTranslationSystem()
        print("✅ 翻譯系統初始化成功")
        
        # 注意：不測試實際API調用，因為需要API密鑰
        print("⚠️ API密鑰測試跳過（需要在實際使用時設置）")
        
        return True
        
    except Exception as e:
        print(f"❌ 翻譯系統初始化失敗: {e}")
        return False

def main():
    """主測試函數"""
    print("🧪 ESP32 AI語音翻譯系統 - 快速測試")
    print("=" * 50)
    
    tests = [
        ("Python庫導入", test_imports),
        ("XTTS-v2模型文件", test_xtts_model),
        ("語音克隆文件", test_voice_files),
        ("主要模塊", test_main_modules),
        ("翻譯系統", test_translation_system),
        ("XTTS模型初始化", test_xtts_initialization)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} - 通過")
            else:
                print(f"❌ {test_name} - 失敗")
        except Exception as e:
            print(f"❌ {test_name} - 錯誤: {e}")
    
    print("\n" + "=" * 50)
    print(f"測試結果: {passed}/{total} 通過")
    
    if passed == total:
        print("🎉 所有測試通過！系統準備就緒！")
        print("\n下一步:")
        print("1. 確保ESP32已燒錄代碼並開機")
        print("2. 運行: python run_voice_translator.py")
        print("3. 開始使用AI語音翻譯系統！")
    else:
        print("⚠️ 部分測試失敗，請修復問題後重新測試")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
