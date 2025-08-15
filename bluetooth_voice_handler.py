#!/usr/bin/env python3
"""
ESP32語音麥克風BLE處理程序 (使用 bleak 庫)
整合原有的AI語音翻譯系統與ESP32 BLE麥克風

主要功能:
- BLE連接管理 (替代傳統藍牙)
- 音頻數據接收 (通過BLE通知)
- 整合現有的語音翻譯系統
- 音頻回放處理

注意事項:
1. 此版本使用 BLE (藍牙低功耗) 而非傳統藍牙
2. ESP32端需要配置相應的BLE服務和特性
3. 需要安裝 bleak 庫: pip install bleak
4. BLE 數據傳輸有大小限制，需要分塊傳送

作者: Your Name
版本: 2.0 (BLE)
日期: 2024
"""

import sys
import platform
import asyncio
import struct
import threading
import time
import queue
import wave
import tempfile
import os
import numpy as np
from datetime import datetime
import logging
from bleak import BleakScanner, BleakClient

# 導入原有的語音翻譯系統
from main import RealTimeVoiceTranslationSystem
import google.generativeai as genai

class ESP32BluetoothHandler:
    def __init__(self):
        # 藍牙配置
        self.device_name = "ESP32-VoiceMic"
        self.device_address = None
        self.client = None
        self.connected = False
        
        # BLE 服務和特性 UUID (需要在ESP32端配置相同的UUID)
        self.service_uuid = "12345678-1234-1234-1234-123456789abc"
        self.audio_char_uuid = "87654321-4321-4321-4321-cba987654321"
        self.command_char_uuid = "11111111-2222-3333-4444-555555555555"
        
        # 音頻參數 (與ESP32匹配)
        self.sample_rate = 16000
        self.channels = 1
        self.sample_width = 2  # 16-bit
        
        # 數據處理隊列
        self.audio_queue = queue.Queue()
        self.playback_queue = queue.Queue()
        self.received_data = bytearray()
        
        # 異步事件循環
        self.loop = None
        self.should_stop = False
        self.threads = []
        
        # 整合語音翻譯系統
        self.translation_system = RealTimeVoiceTranslationSystem()
        
        # 日誌配置
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        print("🎤 ESP32藍牙語音處理器已初始化 (BLE模式)")
    
    async def scan_devices_async(self):
        """異步掃描BLE設備"""
        print("🔍 掃描BLE設備中...")
        
        try:
            devices = await BleakScanner.discover(timeout=10.0)
            
            if not devices:
                print("❌ 未發現任何BLE設備")
                return None
            
            print(f"📱 發現 {len(devices)} 個BLE設備:")
            for device in devices:
                name = device.name or "Unknown"
                print(f"  📱 {name} ({device.address})")
                
                if self.device_name in name:
                    print(f"✅ 找到目標設備: {name}")
                    self.device_address = device.address
                    return device.address
            
            print(f"❌ 未找到設備 '{self.device_name}'")
            return None
            
        except Exception as e:
            print(f"❌ 設備掃描錯誤: {e}")
            return None
    
    def scan_devices(self):
        """掃描藍牙設備 (同步包裝器)"""
        return asyncio.run(self.scan_devices_async())
    
    async def connect_async(self, address=None):
        """異步連接到ESP32 BLE設備"""
        if address:
            self.device_address = address
        
        if not self.device_address:
            print("❌ 未指定設備地址")
            return False
        
        try:
            print(f"📡 正在連接到BLE設備 {self.device_address}...")
            
            # 創建BLE客戶端
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            
            if self.client.is_connected:
                self.connected = True
                print("✅ BLE連接成功！")
                
                # 設置通知回調
                await self.client.start_notify(self.audio_char_uuid, self.notification_handler)
                
                # 啟動數據處理線程
                self.start_threads()
                
                return True
            else:
                print("❌ BLE連接失敗")
                return False
                
        except Exception as e:
            print(f"❌ BLE連接失敗: {e}")
            self.connected = False
            return False
    
    def connect(self, address=None):
        """連接到ESP32設備 (同步包裝器)"""
        return asyncio.run(self.connect_async(address))
    
    async def disconnect_async(self):
        """異步斷開BLE連接"""
        self.should_stop = True
        self.connected = False
        
        # 等待線程結束
        for thread in self.threads:
            thread.join(timeout=3)
        
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(self.audio_char_uuid)
                await self.client.disconnect()
                print("📱 BLE連接已斷開")
            except:
                pass
            self.client = None
    
    def disconnect(self):
        """斷開藍牙連接 (同步包裝器)"""
        if self.loop and self.loop.is_running():
            # 如果事件循環正在運行，創建任務
            asyncio.create_task(self.disconnect_async())
        else:
            # 否則直接運行
            asyncio.run(self.disconnect_async())
    
    def notification_handler(self, sender, data):
        """BLE通知處理器"""
        try:
            # 將接收到的數據添加到緩衝區
            self.received_data.extend(data)
            
            # 檢查是否收到完整的音頻數據包
            self.process_received_data()
            
        except Exception as e:
            self.logger.error(f"通知處理錯誤: {e}")
    
    def process_received_data(self):
        """處理接收到的數據"""
        try:
            # 簡化的數據處理 - 假設數據格式為: [命令字節][數據]
            if len(self.received_data) == 0:
                return
            
            command = self.received_data[0]
            
            if command == ord('A'):  # Audio data
                # 檢查是否有足夠的頭信息
                if len(self.received_data) >= 9:  # 1 byte command + 8 bytes header
                    header = self.received_data[1:9]
                    sample_count, sample_rate = struct.unpack('LL', header)
                    
                    expected_size = 9 + sample_count * 2  # header + audio data
                    
                    if len(self.received_data) >= expected_size:
                        # 提取音頻數據
                        audio_data = self.received_data[9:expected_size]
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                        
                        # 加入處理隊列
                        self.audio_queue.put({
                            'audio': audio_array,
                            'sample_rate': sample_rate,
                            'timestamp': datetime.now()
                        })
                        
                        print(f"✅ BLE音頻數據接收完成: {len(audio_array)} 樣本")
                        
                        # 清除已處理的數據
                        self.received_data = self.received_data[expected_size:]
            
        except Exception as e:
            self.logger.error(f"數據處理錯誤: {e}")
            self.received_data.clear()
    
    def start_threads(self):
        """啟動數據處理線程"""
        self.should_stop = False
        
        # 音頻處理線程
        process_thread = threading.Thread(target=self.audio_process_worker)
        process_thread.daemon = True
        process_thread.start()
        self.threads.append(process_thread)
        
        # 音頻回放線程
        playback_thread = threading.Thread(target=self.audio_playback_worker)
        playback_thread.daemon = True
        playback_thread.start()
        self.threads.append(playback_thread)
        
        print("🔄 BLE數據處理線程已啟動")
    
    # BLE 使用通知機制接收數據，不需要獨立的接收線程
    
    def audio_process_worker(self):
        """音頻處理工作線程"""
        print("🔄 音頻處理線程已啟動")
        
        while not self.should_stop:
            try:
                # 從隊列獲取音頻數據
                audio_data = self.audio_queue.get(timeout=1)
                
                # 保存為臨時WAV文件
                temp_file = self.save_temp_audio(
                    audio_data['audio'], 
                    audio_data['sample_rate']
                )
                
                if temp_file:
                    # 使用原有系統進行翻譯
                    original_text, translated_text = self.process_audio_translation(temp_file)
                    
                    if translated_text:
                        print(f"📝 原文: {original_text}")
                        print(f"🌍 翻譯: {translated_text}")
                        
                        # 語音合成
                        output_audio = self.synthesize_translated_speech(translated_text)
                        
                        if output_audio:
                            # 發送回ESP32播放
                            self.send_audio_to_esp32(output_audio)
                    
                    # 清理臨時文件
                    os.unlink(temp_file)
                
                # 通知ESP32處理完成
                self.send_command('R')  # Ready
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"音頻處理錯誤: {e}")
                self.send_command('E')  # Error
        
        print("🔄 音頻處理線程已停止")
    
    def save_temp_audio(self, audio_array, sample_rate):
        """保存音頻數據為臨時WAV文件"""
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            
            with wave.open(temp_file.name, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(self.sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_array.tobytes())
            
            return temp_file.name
            
        except Exception as e:
            self.logger.error(f"臨時音頻文件保存錯誤: {e}")
            return None
    
    def process_audio_translation(self, audio_file):
        """使用原有系統處理音頻翻譯"""
        try:
            # 檢查翻譯系統是否初始化
            if not self.translation_system.model:
                self.logger.error("翻譯系統未初始化")
                return None, None
            
            # 使用原有的轉錄和翻譯功能
            original_text, translated_text = self.translation_system.transcribe_and_translate_gui(audio_file)
            
            return original_text, translated_text
            
        except Exception as e:
            self.logger.error(f"音頻翻譯錯誤: {e}")
            return None, None
    
    def synthesize_translated_speech(self, text):
        """合成翻譯後的語音"""
        try:
            # 檢查語音合成是否可用
            if not self.translation_system.xtts_model:
                self.logger.error("XTTS模型未載入")
                return None
            
            # 使用原有的語音合成功能
            output_file = self.translation_system.synthesize_speech(text)
            
            if output_file and os.path.exists(output_file):
                # 讀取合成的音頻文件
                with wave.open(output_file, 'rb') as wav_file:
                    audio_data = wav_file.readframes(-1)
                
                # 清理臨時文件
                os.unlink(output_file)
                
                return audio_data
            
            return None
            
        except Exception as e:
            self.logger.error(f"語音合成錯誤: {e}")
            return None
    
    async def send_audio_to_esp32_async(self, audio_data):
        """異步發送合成的音頻到ESP32播放"""
        try:
            if not self.connected or not self.client:
                return
            
            print(f"📤 發送音頻到ESP32 (BLE): {len(audio_data)} 字節")
            
            # 準備播放命令數據包
            command_data = b'P' + struct.pack('L', len(audio_data))
            
            # 分塊發送音頻數據 (BLE特性有大小限制，通常20字節)
            chunk_size = 20
            
            # 發送命令
            await self.client.write_gatt_char(self.command_char_uuid, command_data)
            
            # 分塊發送音頻數據
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                await self.client.write_gatt_char(self.audio_char_uuid, chunk)
                await asyncio.sleep(0.01)  # 小延遲確保穩定傳輸
            
            print("✅ BLE音頻發送完成")
            
        except Exception as e:
            self.logger.error(f"BLE音頻發送錯誤: {e}")
    
    def send_audio_to_esp32(self, audio_data):
        """發送合成的音頻到ESP32播放 (同步包裝器)"""
        if self.loop and self.loop.is_running():
            asyncio.create_task(self.send_audio_to_esp32_async(audio_data))
        else:
            asyncio.run(self.send_audio_to_esp32_async(audio_data))
    
    async def send_command_async(self, command):
        """異步發送命令到ESP32"""
        try:
            if self.connected and self.client:
                command_data = command.encode('ascii')
                await self.client.write_gatt_char(self.command_char_uuid, command_data)
        except Exception as e:
            self.logger.error(f"BLE命令發送錯誤: {e}")
    
    def send_command(self, command):
        """發送命令到ESP32 (同步包裝器)"""
        if self.loop and self.loop.is_running():
            asyncio.create_task(self.send_command_async(command))
        else:
            asyncio.run(self.send_command_async(command))
    
    async def send_status_async(self):
        """異步發送狀態信息到ESP32"""
        try:
            status_data = struct.pack('BBB', 
                                    1 if self.connected else 0,
                                    1 if self.translation_system.model else 0,
                                    1 if self.translation_system.xtts_model else 0)
            command_data = b'S' + status_data
            await self.client.write_gatt_char(self.command_char_uuid, command_data)
        except Exception as e:
            self.logger.error(f"BLE狀態發送錯誤: {e}")
    
    def send_status(self):
        """發送狀態信息到ESP32 (同步包裝器)"""
        if self.loop and self.loop.is_running():
            asyncio.create_task(self.send_status_async())
        else:
            asyncio.run(self.send_status_async())
    
    def audio_playback_worker(self):
        """音頻回放工作線程（備用）"""
        print("🔊 音頻回放線程已啟動")
        
        while not self.should_stop:
            try:
                # 這個線程主要用於本地音頻播放（如果需要）
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"音頻回放錯誤: {e}")
        
        print("🔊 音頻回放線程已停止")
    
    def setup_translation_system(self, api_key, source_lang='zh', target_lang='en', voice_path=None):
        """設置翻譯系統參數"""
        try:
            # 設置API Key
            genai.configure(api_key=api_key)
            self.translation_system.gemini_api_key = api_key
            self.translation_system.model = genai.GenerativeModel('gemini-2.0-flash-exp')
            
            # 設置語言
            self.translation_system.source_language = source_lang
            self.translation_system.target_language = target_lang
            
            # 載入XTTS模型
            if self.translation_system.load_xtts_model():
                print("✅ XTTS模型載入成功")
            else:
                print("❌ XTTS模型載入失敗")
            
            # 設置語音克隆文件
            if voice_path and os.path.exists(voice_path):
                self.translation_system.cloned_voice_path = voice_path
                self.translation_system.is_voice_cloned = True
                print(f"✅ 語音克隆文件已設置: {voice_path}")
            
            print("✅ 翻譯系統設置完成")
            return True
            
        except Exception as e:
            self.logger.error(f"翻譯系統設置錯誤: {e}")
            return False


class ESP32VoiceMicrophoneApp:
    """ESP32語音麥克風應用程序主類"""
    
    def __init__(self):
        self.bluetooth_handler = ESP32BluetoothHandler()
        self.running = False
    
    def setup(self):
        """設置應用程序"""
        print("🎤 ESP32語音麥克風系統設置")
        print("=" * 50)
        
        # 獲取API Key
        api_key = input("請輸入Gemini API Key: ").strip()
        if not api_key:
            print("❌ API Key不能為空")
            return False
        
        # 選擇語言
        print("\n支持的語言:")
        languages = {
            'zh': '中文', 'en': '英文', 'ja': '日文', 'ko': '韓文',
            'es': '西班牙文', 'fr': '法文', 'de': '德文', 'it': '意大利文', 'pt': '葡萄牙文'
        }
        
        for code, name in languages.items():
            print(f"  {code}: {name}")
        
        source_lang = input("\n輸入原始語言代碼 [zh]: ").strip() or 'zh'
        target_lang = input("輸入目標語言代碼 [en]: ").strip() or 'en'
        
        # 選擇語音克隆文件
        voice_files = []
        if os.path.exists("cloned_voices"):
            voice_files = [f for f in os.listdir("cloned_voices") if f.endswith('.wav')]
        
        voice_path = None
        if voice_files:
            print("\n可用的語音文件:")
            for i, filename in enumerate(voice_files):
                print(f"  {i+1}: {filename}")
            
            try:
                choice = input(f"選擇語音文件 [1]: ").strip() or '1'
                index = int(choice) - 1
                if 0 <= index < len(voice_files):
                    voice_path = os.path.join("cloned_voices", voice_files[index])
            except ValueError:
                pass
        
        # 設置翻譯系統
        if not self.bluetooth_handler.setup_translation_system(
            api_key, source_lang, target_lang, voice_path):
            return False
        
        print("✅ 系統設置完成")
        return True
    
    def connect_esp32(self):
        """連接ESP32設備"""
        print("\n📱 連接ESP32設備")
        print("=" * 30)
        
        # 掃描設備
        device_address = self.bluetooth_handler.scan_devices()
        
        if not device_address:
            # 手動輸入地址
            device_address = input("請輸入ESP32設備地址 (例: XX:XX:XX:XX:XX:XX): ").strip()
        
        if device_address:
            return self.bluetooth_handler.connect(device_address)
        
        return False
    
    def run(self):
        """運行主程序"""
        print("🎤 ESP32 AI語音翻譯麥克風系統")
        print("=" * 50)
        
        try:
            # 系統設置
            if not self.setup():
                print("❌ 系統設置失敗")
                return
            
            # 連接ESP32
            if not self.connect_esp32():
                print("❌ ESP32連接失敗")
                return
            
            print("\n✅ 系統就緒！")
            print("現在可以使用ESP32設備進行語音翻譯了")
            print("按 Ctrl+C 退出程序")
            
            self.running = True
            
            # 主循環
            while self.running:
                time.sleep(1)
                
                # 檢查連接狀態
                if not self.bluetooth_handler.connected:
                    print("❌ 藍牙連接丟失")
                    break
            
        except KeyboardInterrupt:
            print("\n👋 用戶中斷程序")
        except Exception as e:
            print(f"❌ 運行錯誤: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """關閉程序"""
        print("\n🔄 正在關閉系統...")
        self.running = False
        self.bluetooth_handler.disconnect()
        print("✅ 系統已關閉")


if __name__ == "__main__":
    app = ESP32VoiceMicrophoneApp()
    app.run()
