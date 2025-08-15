#!/usr/bin/env python3
"""
ESP32 AI語音翻譯麥克風專案設置腳本

此腳本將自動設置整個專案環境，包括：
- 檢查依賴項
- 安裝必要的套件
- 配置系統參數
- 執行初始測試

使用方法:
    python setup_esp32_project.py
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

class ESP32ProjectSetup:
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.system = platform.system()
        self.python_version = sys.version_info
        
        print("🎤 ESP32 AI語音翻譯麥克風專案設置")
        print("=" * 50)
        print(f"專案目錄: {self.project_root}")
        print(f"作業系統: {self.system}")
        print(f"Python 版本: {self.python_version.major}.{self.python_version.minor}")
        print()
    
    def check_python_version(self):
        """檢查 Python 版本"""
        print("🐍 檢查 Python 版本...")
        
        if self.python_version < (3, 10):
            print("❌ 需要 Python 3.10 或更新版本")
            print(f"   當前版本: {self.python_version.major}.{self.python_version.minor}")
            return False
        
        print("✅ Python 版本符合要求")
        return True
    
    def check_system_dependencies(self):
        """檢查系統依賴項"""
        print("\n🔧 檢查系統依賴項...")
        
        dependencies = {
            'Linux': ['bluetooth', 'libbluetooth-dev', 'python3-dev'],
            'Darwin': [],  # macOS
            'Windows': []
        }
        
        if self.system == 'Linux':
            print("📦 Linux 系統檢查藍牙依賴...")
            try:
                subprocess.run(['which', 'bluetoothctl'], 
                             check=True, capture_output=True)
                print("✅ 藍牙工具已安裝")
            except subprocess.CalledProcessError:
                print("⚠️ 藍牙工具未安裝，請執行:")
                print("   sudo apt-get install bluetooth bluez")
                
        elif self.system == 'Darwin':
            print("🍎 macOS 系統檢查...")
            print("✅ 請確保在系統偏好設定中啟用藍牙")
            
        elif self.system == 'Windows':
            print("🪟 Windows 系統檢查...")
            print("✅ 請確保電腦具備藍牙功能")
    
    def setup_virtual_environment(self):
        """設置虛擬環境"""
        print("\n🏠 設置虛擬環境...")
        
        venv_path = self.project_root / "esp32_env"
        
        if venv_path.exists():
            print("✅ 虛擬環境已存在")
            return True
        
        try:
            print("📦 創建虛擬環境...")
            subprocess.run([sys.executable, '-m', 'venv', str(venv_path)], 
                         check=True)
            print("✅ 虛擬環境創建成功")
            
            # 激活虛擬環境的說明
            if self.system == 'Windows':
                activate_cmd = f"{venv_path}\\Scripts\\activate"
            else:
                activate_cmd = f"source {venv_path}/bin/activate"
            
            print(f"💡 激活虛擬環境: {activate_cmd}")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 虛擬環境創建失敗: {e}")
            return False
    
    def install_python_dependencies(self):
        """安裝 Python 依賴項"""
        print("\n📚 安裝 Python 依賴項...")
        
        requirements_file = self.project_root / "requirements.txt"
        
        if not requirements_file.exists():
            print("❌ 找不到 requirements.txt")
            return False
        
        try:
            # 更新 pip
            print("⬆️ 更新 pip...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], 
                         check=True)
            
            # 安裝基本依賴
            print("📦 安裝基本依賴...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 
                          str(requirements_file)], check=True)
            
            # 安裝藍牙支援
            print("📡 安裝藍牙支援...")
            bluetooth_packages = ['pybluez']
            
            if self.system == 'Windows':
                bluetooth_packages.append('bleak')  # Windows 藍牙替代方案
            
            for package in bluetooth_packages:
                try:
                    subprocess.run([sys.executable, '-m', 'pip', 'install', package], 
                                 check=True)
                    print(f"✅ {package} 安裝成功")
                except subprocess.CalledProcessError:
                    print(f"⚠️ {package} 安裝失敗，可能需要手動安裝")
            
            print("✅ Python 依賴項安裝完成")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 依賴項安裝失敗: {e}")
            return False
    
    def check_models_and_files(self):
        """檢查模型文件和目錄"""
        print("\n🤖 檢查模型文件...")
        
        # 檢查 XTTS 模型目錄
        xtts_path = self.project_root / "XTTS-v2"
        if xtts_path.exists():
            config_file = xtts_path / "config.json"
            model_file = xtts_path / "model.pth"
            
            if config_file.exists() and model_file.exists():
                print("✅ XTTS-v2 模型文件完整")
            else:
                print("⚠️ XTTS-v2 模型文件不完整")
                print("   請確保下載完整的模型文件")
        else:
            print("⚠️ XTTS-v2 模型目錄不存在")
            print("   請下載 XTTS-v2 模型到專案目錄")
        
        # 檢查語音克隆目錄
        voices_path = self.project_root / "cloned_voices"
        if not voices_path.exists():
            print("📁 創建語音克隆目錄...")
            voices_path.mkdir(exist_ok=True)
            print("✅ cloned_voices 目錄已創建")
        else:
            voice_files = list(voices_path.glob("*.wav"))
            if voice_files:
                print(f"✅ 找到 {len(voice_files)} 個語音文件")
            else:
                print("💡 cloned_voices 目錄為空，請先錄製語音克隆樣本")
    
    def create_config_file(self):
        """創建配置文件"""
        print("\n⚙️ 創建配置文件...")
        
        config_content = """# ESP32 語音麥克風配置文件
# 請根據您的需求修改以下設置

[bluetooth]
device_name = ESP32-VoiceMic
scan_timeout = 10
connection_timeout = 30

[audio]
sample_rate = 16000
channels = 1
bit_depth = 16
buffer_size = 1024

[translation]
source_language = zh
target_language = en
api_provider = gemini

[voice]
enable_cloning = true
voice_similarity_threshold = 0.8

[system]
log_level = INFO
auto_connect = true
retry_attempts = 3
"""
        
        config_file = self.project_root / "config.ini"
        
        if not config_file.exists():
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            print("✅ 配置文件已創建: config.ini")
        else:
            print("✅ 配置文件已存在")
    
    def run_system_test(self):
        """執行系統測試"""
        print("\n🧪 執行系統測試...")
        
        # 測試藍牙功能
        print("📡 測試藍牙功能...")
        try:
            import bluetooth
            print("✅ 藍牙模組導入成功")
            
            # 簡單的設備掃描測試
            try:
                devices = bluetooth.discover_devices(duration=1, lookup_names=False)
                print(f"✅ 藍牙掃描功能正常 (發現 {len(devices)} 個設備)")
            except Exception as e:
                print(f"⚠️ 藍牙掃描測試失敗: {e}")
                
        except ImportError:
            print("❌ 藍牙模組導入失敗")
            print("   請檢查 pybluez 安裝")
        
        # 測試語音處理模組
        print("🎤 測試語音處理模組...")
        try:
            import numpy as np
            import scipy.io.wavfile
            print("✅ 音頻處理模組正常")
        except ImportError as e:
            print(f"❌ 音頻處理模組錯誤: {e}")
        
        # 測試 AI 模組
        print("🤖 測試 AI 模組...")
        try:
            import google.generativeai as genai
            print("✅ Gemini API 模組正常")
        except ImportError as e:
            print(f"❌ Gemini API 模組錯誤: {e}")
    
    def print_next_steps(self):
        """顯示後續步驟"""
        print("\n🎯 後續步驟:")
        print("=" * 50)
        
        print("1. 📱 ESP32 硬體設置:")
        print("   - 按照 wiring_guide.md 完成硬體連接")
        print("   - 使用 Arduino IDE 上傳 esp32_voice_mic.ino")
        
        print("\n2. 🔑 API 設置:")
        print("   - 獲取 Gemini API Key: https://makersuite.google.com/app/apikey")
        print("   - 在運行程式時輸入 API Key")
        
        print("\n3. 🎭 語音克隆:")
        print("   - 運行原有的 main.py 錄製語音樣本")
        print("   - 或直接將 WAV 文件放入 cloned_voices/ 目錄")
        
        print("\n4. 🚀 啟動系統:")
        print("   - 啟動 ESP32 設備")
        print("   - 執行: python bluetooth_voice_handler.py")
        
        print("\n5. 📖 詳細說明:")
        print("   - 閱讀 ESP32_VoiceMic_README.md")
        print("   - 查看 wiring_guide.md 了解硬體接線")
        
        print("\n✨ 祝您使用愉快！")
    
    def run_setup(self):
        """執行完整設置流程"""
        try:
            # 檢查 Python 版本
            if not self.check_python_version():
                return False
            
            # 檢查系統依賴
            self.check_system_dependencies()
            
            # 設置虛擬環境
            if not self.setup_virtual_environment():
                return False
            
            # 安裝 Python 依賴
            if not self.install_python_dependencies():
                return False
            
            # 檢查模型文件
            self.check_models_and_files()
            
            # 創建配置文件
            self.create_config_file()
            
            # 執行系統測試
            self.run_system_test()
            
            # 顯示後續步驟
            self.print_next_steps()
            
            print("\n🎉 專案設置完成！")
            return True
            
        except KeyboardInterrupt:
            print("\n\n⏹️ 設置被用戶中斷")
            return False
        except Exception as e:
            print(f"\n❌ 設置過程中發生錯誤: {e}")
            return False


if __name__ == "__main__":
    setup = ESP32ProjectSetup()
    success = setup.run_setup()
    
    if success:
        print("\n🎤 ESP32 AI語音翻譯麥克風專案已準備就緒！")
        sys.exit(0)
    else:
        print("\n❌ 專案設置未完成，請檢查錯誤訊息")
        sys.exit(1)
