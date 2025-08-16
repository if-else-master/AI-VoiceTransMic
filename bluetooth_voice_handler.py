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
import signal
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
        
        # 先初始化日誌配置
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # 異步事件循環管理
        self.loop = None
        self.loop_thread = None
        self.should_stop = False
        self.threads = []
        self._shutdown_complete = threading.Event()
        self._loop_ready = threading.Event()
        
        # 連接穩定性管理
        self.connection_monitor_thread = None
        self.last_heartbeat = time.time()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.heartbeat_interval = 10  # 秒
        
        # 整合語音翻譯系統
        self.translation_system = RealTimeVoiceTranslationSystem()
        
        # 啟動持久化事件循環
        self._start_persistent_event_loop()
        
        print("🎤 ESP32藍牙語音處理器已初始化 (BLE模式)")
    
    def _start_persistent_event_loop(self):
        """啟動持久化的事件循環線程"""
        def event_loop_worker():
            try:
                # 創建新的事件循環
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                
                # 標記事件循環已準備好
                self._loop_ready.set()
                
                self.logger.info("持久化事件循環已啟動")
                
                # 運行事件循環直到被停止
                self.loop.run_forever()
                
            except Exception as e:
                self.logger.error(f"事件循環錯誤: {e}")
            finally:
                if self.loop and not self.loop.is_closed():
                    self.loop.close()
                self.logger.info("事件循環已關閉")
        
        # 啟動事件循環線程
        self.loop_thread = threading.Thread(target=event_loop_worker, daemon=True)
        self.loop_thread.start()
        
        # 等待事件循環準備好
        self._loop_ready.wait(timeout=5)
        
        if not self._loop_ready.is_set():
            raise RuntimeError("事件循環啟動失敗")
    
    def _run_async_task(self, coro, timeout=10):
        """在持久化事件循環中運行異步任務"""
        if not self.loop or self.loop.is_closed():
            raise RuntimeError("事件循環不可用")
        
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)
    
    async def scan_devices_async(self):
        """異步掃描BLE設備"""
        print("🔍 掃描BLE設備中...")
        
        try:
            devices = await BleakScanner.discover(timeout=10.0)
            
            if not devices:
                print("❌ 未發現任何BLE設備")
                return None
            
            print(f"📱 發現 {len(devices)} 個BLE設備:")
            esp32_devices = []
            
            for i, device in enumerate(devices):
                name = device.name or "Unknown"
                device_type = "其他"
                
                # 識別ESP32設備
                if name and ("ESP32" in name.upper() or "VOICE" in name.upper() or "MIC" in name.upper()):
                    device_type = "ESP32設備"
                    esp32_devices.append(i)
                    
                print(f"  {i+1}. {name} ({device.address}) - {device_type}")
                
                # 自動選擇ESP32設備 (註釋掉自動連接，總是讓用戶選擇)
                # if self.device_name in name:
                #     print(f"✅ 找到目標設備: {name}")
                #     self.device_address = device.address
                #     return device.address
            
            # 如果沒有自動找到，讓用戶選擇
            if esp32_devices:
                print(f"\n💡 建議選擇: {', '.join([str(i+1) for i in esp32_devices])} (ESP32設備)")
            else:
                print("\n⚠️ 未找到ESP32設備，請確認設備已開啟並在廣播")
            
            return devices
            
        except Exception as e:
            print(f"❌ 設備掃描錯誤: {e}")
            return None
    
    def scan_devices(self):
        """掃描藍牙設備 (同步包裝器)"""
        try:
            return self._run_async_task(self.scan_devices_async(), timeout=15)
        except Exception as e:
            print(f"❌ 掃描設備失敗: {e}")
            return None
    
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
            self.client = BleakClient(self.device_address, timeout=20.0)
            await self.client.connect()
            
            if self.client.is_connected:
                self.connected = True
                print("✅ BLE連接成功！")
                
                # 設置通知回調
                try:
                    await self.client.start_notify(self.audio_char_uuid, self.notification_handler)
                    print("✅ BLE通知設置成功")
                except Exception as e:
                    print(f"⚠️ 設置BLE通知失敗: {e}")
                    # 繼續執行，某些情況下仍可能工作
                
                # 清空接收緩衝區
                self.received_data.clear()
                
                # 啟動數據處理線程
                self.start_threads()
                
                # 啟動連接監控
                self.start_connection_monitor()
                
                # 重置重連計數器
                self.reconnect_attempts = 0
                
                return True
            else:
                print("❌ BLE連接失敗")
                return False
                
        except Exception as e:
            print(f"❌ BLE連接失敗: {e}")
            self.connected = False
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
                self.client = None
            return False
    
    def connect(self, address=None):
        """連接到ESP32設備 (同步包裝器)"""
        try:
            return self._run_async_task(self.connect_async(address), timeout=30)
        except Exception as e:
            self.logger.error(f"連接錯誤: {e}")
            return False
    
    async def disconnect_async(self):
        """異步斷開BLE連接"""
        self.should_stop = True
        self.connected = False
        
        # 先停止BLE通知和連接
        if self.client:
            try:
                if self.client.is_connected:
                    await self.client.stop_notify(self.audio_char_uuid)
                    await self.client.disconnect()
                    print("📱 BLE連接已斷開")
            except Exception as e:
                self.logger.error(f"BLE斷開錯誤: {e}")
            finally:
                self.client = None
        
        # 等待線程結束
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2)
        
        self.threads.clear()
        self._shutdown_complete.set()
    
    def disconnect(self):
        """斷開藍牙連接 (同步包裝器)"""
        try:
            # 設置停止標志
            self.should_stop = True
            self.connected = False
            
            # 使用新的事件循環來處理斷開
            if self.client:
                try:
                    # 創建新的事件循環來安全地處理斷開
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self._safe_disconnect())
                    loop.close()
                except Exception as e:
                    self.logger.error(f"斷開連接錯誤: {e}")
                finally:
                    self.client = None
            
            # 等待所有線程結束
            for thread in self.threads:
                if thread.is_alive():
                    thread.join(timeout=2)
            
            self.threads.clear()
            print("📱 BLE連接處理完成")
            
        except Exception as e:
            self.logger.error(f"斷開連接時發生錯誤: {e}")
    
    async def _safe_disconnect(self):
        """安全地斷開BLE連接"""
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(self.audio_char_uuid)
                await self.client.disconnect()
            except Exception as e:
                self.logger.error(f"安全斷開錯誤: {e}")
    
    def safe_shutdown(self):
        """安全關閉整個藍牙處理器"""
        try:
            self.should_stop = True
            
            # 等待線程結束
            for thread in self.threads:
                if thread.is_alive():
                    thread.join(timeout=3)
            
            # 安全關閉事件循環
            if self.loop and not self.loop.is_closed():
                try:
                    # 停止事件循環
                    self.loop.call_soon_threadsafe(self.loop.stop)
                    
                    # 等待循環線程結束
                    if self.loop_thread and self.loop_thread.is_alive():
                        self.loop_thread.join(timeout=3)
                        
                except Exception as e:
                    self.logger.error(f"關閉事件循環錯誤: {e}")
            
            print("📱 藍牙處理器已安全關閉")
            
        except Exception as e:
            self.logger.error(f"安全關閉錯誤: {e}")
            print("📱 藍牙處理器已強制關閉")
    
    def notification_handler(self, sender, data):
        """BLE通知處理器"""
        try:
            # 檢查是否應該停止或事件循環已關閉
            if self.should_stop or not self.connected or (self.loop and self.loop.is_closed()):
                return
                
            # 將接收到的數據添加到緩衝區
            self.received_data.extend(data)
            print(f"📶 BLE接收數據: {len(data)} 字節, 緩衝區總計: {len(self.received_data)} 字節")
            
            # 檢查是否收到完整的音頻數據包
            self.process_received_data()
            
        except Exception as e:
            if not self.should_stop:  # 只在非關閉狀態下記錄錯誤
                self.logger.error(f"通知處理錯誤: {e}")
            # 不要在這裡斷開連接，只記錄錯誤
    
    def process_received_data(self):
        """處理接收到的數據"""
        try:
            # 檢查數據是否足夠
            if len(self.received_data) == 0:
                return
            
            command = self.received_data[0]
            
            if command == ord('A'):  # Audio data
                # 檢查是否有足夠的頭信息 (1字節命令 + 4字節樣本數 + 4字節採樣率)
                if len(self.received_data) >= 9:
                    # 使用小端序解析頭信息（ESP32默認小端序）
                    header = self.received_data[1:9]
                    sample_count = struct.unpack('<I', header[0:4])[0]  # 無符號32位整數
                    sample_rate = struct.unpack('<I', header[4:8])[0]   # 無符號32位整數
                    
                    expected_size = 9 + sample_count * 2  # header + audio data
                    
                    print(f"🎵 BLE音頻頭信息: 樣本數={sample_count}, 採樣率={sample_rate}, 預期大小={expected_size}")
                    
                    # 檢查數據合理性
                    if sample_count > 1000000 or sample_rate > 100000:  # 異常大的值
                        print(f"❌ 音頻頭信息異常，清除緩衝區")
                        self.received_data.clear()
                        return
                    
                    if len(self.received_data) >= expected_size:
                        # 提取音頻數據
                        audio_data = self.received_data[9:expected_size]
                        
                        try:
                            audio_array = np.frombuffer(audio_data, dtype=np.int16)
                            
                            print(f"✅ BLE音頻數據接收完成: {len(audio_array)} 樣本, 實際採樣率: {sample_rate}")
                            print(f"📊 音頻統計: 最大值={np.max(audio_array)}, 最小值={np.min(audio_array)}, 平均值={np.mean(audio_array):.1f}")
                            
                            # 檢查音頻數據是否有效
                            if len(audio_array) > 0 and np.any(audio_array != 0):
                                # 顯示錄音完成通知
                                duration = len(audio_array) / sample_rate
                                print(f"\n{'='*60}")
                                print(f"⚡ 即時音頻片段接收！時長: {duration:.1f}秒")
                                print(f"📊 音頻品質: {len(audio_array)} 樣本, {sample_rate}Hz")
                                print(f"🚀 開始即時AI語音翻譯處理...")
                                print(f"{'='*60}")
                                
                                # 加入處理隊列
                                self.audio_queue.put({
                                    'audio': audio_array,
                                    'sample_rate': sample_rate,
                                    'timestamp': datetime.now()
                                })
                            else:
                                print("⚠️ 音頻數據為空或全零，跳過處理")
                            
                            # 清除已處理的數據
                            self.received_data = self.received_data[expected_size:]
                            
                        except Exception as audio_error:
                            print(f"❌ 音頻數據解析錯誤: {audio_error}")
                            self.received_data.clear()
                            
                    else:
                        print(f"⏳ 等待更多音頻數據: {len(self.received_data)}/{expected_size}")
                        
                        # 防止緩衝區無限增長
                        if len(self.received_data) > 1000000:  # 1MB限制
                            print("⚠️ 接收緩衝區過大，清除數據")
                            self.received_data.clear()
                else:
                    print(f"⏳ 等待音頻頭信息: {len(self.received_data)}/9")
            else:
                print(f"⚠️ 未知命令: {command} (0x{command:02x})")
                # 嘗試找到下一個有效的命令開始位置
                next_a = self.received_data.find(b'A', 1)
                if next_a > 0:
                    print(f"🔍 找到下一個音頻命令位置: {next_a}")
                    self.received_data = self.received_data[next_a:]
                else:
                    self.received_data.clear()
            
        except Exception as e:
            self.logger.error(f"數據處理錯誤: {e}")
            print(f"❌ 數據處理異常，緩衝區長度: {len(self.received_data)}")
            # 清除緩衝區重新開始
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
    
    def start_connection_monitor(self):
        """啟動連接監控線程"""
        if self.connection_monitor_thread and self.connection_monitor_thread.is_alive():
            return
        
        self.connection_monitor_thread = threading.Thread(target=self.connection_monitor_worker)
        self.connection_monitor_thread.daemon = True
        self.connection_monitor_thread.start()
        print("🔄 BLE連接監控線程已啟動")
    
    def connection_monitor_worker(self):
        """連接監控工作線程"""
        while not self.should_stop and self.connected:
            try:
                time.sleep(self.heartbeat_interval)
                
                # 檢查連接狀態
                if self.client and not self.client.is_connected:
                    print("⚠️ 檢測到BLE連接斷開，嘗試重連...")
                    self.handle_connection_lost()
                    break
                
                # 發送心跳
                if self.connected:
                    try:
                        self.send_status()
                        self.last_heartbeat = time.time()
                    except Exception as e:
                        print(f"⚠️ 心跳發送失敗: {e}")
                        self.handle_connection_lost()
                        break
                        
            except Exception as e:
                self.logger.error(f"連接監控錯誤: {e}")
                time.sleep(5)
        
        print("🔄 連接監控線程已停止")
    
    def handle_connection_lost(self):
        """處理連接丟失"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            print(f"❌ 已達到最大重連次數 ({self.max_reconnect_attempts})，停止重連")
            self.connected = False
            return
        
        self.reconnect_attempts += 1
        print(f"🔄 嘗試重連 ({self.reconnect_attempts}/{self.max_reconnect_attempts})...")
        
        # 清理當前連接
        self.connected = False
        if self.client:
            try:
                # 使用新事件循環處理斷開
                self._run_async_task(self._safe_disconnect(), timeout=5)
            except:
                pass
        
        # 等待一段時間後重連
        time.sleep(5)
        
        # 嘗試重連
        if self.device_address:
            success = self.connect(self.device_address)
            if success:
                print("✅ 重連成功！")
            else:
                print("❌ 重連失敗")
                # 繼續嘗試重連
                threading.Thread(target=self.handle_connection_lost, daemon=True).start()
    
    # BLE 使用通知機制接收數據，不需要獨立的接收線程
    
    def audio_process_worker(self):
        """音頻處理工作線程 - 實現即時AI語音克隆翻譯"""
        print("🔄 AI語音克隆翻譯處理線程已啟動")
        
        while not self.should_stop:
            try:
                # 從隊列獲取音頻數據
                audio_data = self.audio_queue.get(timeout=1)
                
                start_time = time.time()
                print(f"🎤 開始處理音頻: {len(audio_data['audio'])} 樣本")
                
                # 保存為臨時WAV文件
                temp_file = self.save_temp_audio(
                    audio_data['audio'], 
                    audio_data['sample_rate']
                )
                
                if temp_file:
                    print("📝 Step 1: 語音轉文字...")
                    
                    # 使用原有系統進行轉錄和翻譯
                    original_text, translated_text = self.process_audio_translation(temp_file)
                    
                    if original_text and translated_text:
                        process_time = time.time() - start_time
                        
                        # 在Terminal中顯示美化的逐字稿和翻譯結果
                        self.display_transcription_results(original_text, translated_text, process_time)
                        
                        # 立即發送翻譯結果到ESP32 LCD顯示
                        print("📟 Step 2: 更新LCD顯示...")
                        self.send_text_to_lcd(original_text, translated_text)
                        
                        # AI語音克隆合成
                        print("🤖 Step 3: AI語音克隆合成...")
                        synthesis_start = time.time()
                        output_audio = self.synthesize_translated_speech(translated_text)
                        synthesis_time = time.time() - synthesis_start
                        
                        if output_audio:
                            print(f"🎵 語音合成完成 ({synthesis_time:.1f}s): {len(output_audio)} 字節")
                            
                            # 立即發送回ESP32播放 (即時播放)
                            print("📤 Step 4: 即時發送語音到ESP32播放...")
                            send_start = time.time()
                            
                            # 非阻塞式發送，讓處理能夠繼續
                            threading.Thread(
                                target=self.send_audio_to_esp32_async_wrapper, 
                                args=(output_audio,),
                                daemon=True
                            ).start()
                            
                            send_time = time.time() - send_start
                            total_time = time.time() - start_time
                            print(f"⚡ 即時處理完成 (總計 {total_time:.1f}s: 轉錄 {process_time:.1f}s + 合成 {synthesis_time:.1f}s + 發送 {send_time:.3f}s)")
                        else:
                            print("❌ 語音合成失敗")
                            self.send_command('E')  # Error
                    else:
                        print("❌ 語音轉錄或翻譯失敗")
                        self.send_command('E')  # Error
                    
                    # 清理臨時文件
                    try:
                        os.unlink(temp_file)
                    except:
                        pass
                else:
                    print("❌ 臨時音頻文件創建失敗")
                    self.send_command('E')  # Error
                
                # 不發送Ready信號，保持系統持續監聽
                # self.send_command('R')  # Ready - 註釋掉以實現連續監聽
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"音頻處理錯誤: {e}")
                print(f"❌ 音頻處理異常: {e}")
                print(f"🔍 錯誤詳情: {type(e).__name__}")
                # 不要因為處理錯誤就斷開連接，只發送錯誤信號
                try:
                    self.send_command('E')  # Error
                except Exception as send_error:
                    print(f"⚠️ 發送錯誤命令失敗: {send_error}")
        
        print("🔄 AI語音克隆翻譯處理線程已停止")
    
    def display_transcription_results(self, original_text, translated_text, process_time):
        """在Terminal中簡潔顯示逐字稿和翻譯結果"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 簡潔的debug格式顯示
        print(f"\n[{timestamp}] 處理時間: {process_time:.1f}秒")
        print(f"原逐字稿：{original_text}")
        print(f"翻譯後的內容：{translated_text}")
        print("-" * 60)
        
        # 記錄到日誌文件（可選）
        self.log_transcription(timestamp, original_text, translated_text, process_time)
        
    def wrap_text(self, text, max_width):
        """將文本按指定寬度分行"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            # 檢查當前行加上新單詞是否超過最大寬度
            test_line = current_line + (" " if current_line else "") + word
            if len(test_line.encode('utf-8')) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
            
        return lines if lines else [text]
    
    def log_transcription(self, timestamp, original_text, translated_text, process_time):
        """將轉錄結果記錄到日誌文件"""
        try:
            log_filename = f"voice_translation_log_{datetime.now().strftime('%Y%m%d')}.txt"
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(f"\n[{timestamp}] 處理時間: {process_time:.1f}s\n")
                f.write(f"原文: {original_text}\n")
                f.write(f"翻譯: {translated_text}\n")
                f.write("-" * 50 + "\n")
        except Exception as e:
            self.logger.error(f"日誌記錄錯誤: {e}")
    
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
        """使用XTTS-v2進行AI語音克隆合成"""
        try:
            # 檢查XTTS模型是否可用
            if not self.translation_system.xtts_model:
                self.logger.error("XTTS-v2模型未載入")
                return None
            
            print(f"🤖 使用XTTS-v2進行語音克隆合成: '{text}'")
            
            # 使用語音克隆功能合成
            if self.translation_system.is_voice_cloned and self.translation_system.cloned_voice_path:
                print(f"🎭 使用克隆語音: {self.translation_system.cloned_voice_path}")
                output_file = self.translation_system.synthesize_speech_with_clone(text)
            else:
                print("🎤 使用默認語音合成")
                output_file = self.translation_system.synthesize_speech(text)
            
            if output_file and os.path.exists(output_file):
                print(f"✅ 語音合成文件生成: {output_file}")
                
                # 讀取合成的音頻文件
                with wave.open(output_file, 'rb') as wav_file:
                    frames = wav_file.getframerate()
                    sample_width = wav_file.getsampwidth()
                    channels = wav_file.getnchannels()
                    audio_data = wav_file.readframes(-1)
                    
                    print(f"📊 音頻參數: {frames}Hz, {sample_width*8}bit, {channels}ch, {len(audio_data)}字節")
                
                # 清理臨時文件
                try:
                    os.unlink(output_file)
                except:
                    pass
                
                return audio_data
            
            print("❌ 語音合成文件生成失敗")
            return None
            
        except Exception as e:
            self.logger.error(f"XTTS-v2語音合成錯誤: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def send_audio_to_esp32_async(self, audio_data):
        """異步發送合成的音頻到ESP32播放"""
        try:
            if not self.connected or not self.client:
                print("❌ BLE未連接，無法發送音頻")
                return
            
            print(f"📤 發送音頻到ESP32 (BLE): {len(audio_data)} 字節")
            
            # 準備播放命令數據包 (4字節小端序音頻大小)
            command_data = b'P' + struct.pack('<L', len(audio_data))
            
            print(f"📦 發送音頻頭命令: {len(command_data)} 字節")
            
            # 發送命令頭
            await self.client.write_gatt_char(self.command_char_uuid, command_data)
            await asyncio.sleep(0.05)  # 給ESP32時間處理命令
            
            # 分塊發送音頻數據 (BLE限制通常是20字節)
            chunk_size = 20
            total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
            
            print(f"📤 開始發送音頻數據，共 {total_chunks} 個數據塊")
            
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                chunk_num = i // chunk_size + 1
                
                try:
                    await self.client.write_gatt_char(self.audio_char_uuid, chunk)
                    if chunk_num % 50 == 0:  # 每50個塊報告一次進度
                        print(f"📤 音頻發送進度: {chunk_num}/{total_chunks}")
                    await asyncio.sleep(0.005)  # 減少延遲以提高傳輸速度
                except Exception as chunk_error:
                    print(f"❌ 發送數據塊 {chunk_num} 失敗: {chunk_error}")
                    break
            
            print("✅ BLE音頻發送完成")
            
        except Exception as e:
            self.logger.error(f"BLE音頻發送錯誤: {e}")
    
    def send_audio_to_esp32(self, audio_data):
        """發送合成的音頻到ESP32播放 (同步包裝器)"""
        try:
            if self.connected and self.client:
                self._run_async_task(self.send_audio_to_esp32_async(audio_data), timeout=10)
        except Exception as e:
            self.logger.error(f"發送音頻錯誤: {e}")
    
    def send_audio_to_esp32_async_wrapper(self, audio_data):
        """非阻塞音頻發送包裝器"""
        try:
            if self.connected and self.client:
                print(f"🎵 非阻塞發送音頻: {len(audio_data)} 字節")
                self._run_async_task(self.send_audio_to_esp32_async(audio_data), timeout=15)
                print(f"✅ 音頻發送完成")
        except Exception as e:
            print(f"❌ 非阻塞音頻發送錯誤: {e}")
            self.logger.error(f"非阻塞音頻發送錯誤: {e}")
    
    async def send_command_async(self, command):
        """異步發送命令到ESP32"""
        try:
            if self.connected and self.client and not self.should_stop:
                command_data = command.encode('ascii')
                print(f"📤 發送命令到ESP32: '{command}' ({len(command_data)} 字節)")
                await self.client.write_gatt_char(self.command_char_uuid, command_data)
                print(f"✅ 命令發送成功: '{command}'")
        except Exception as e:
            print(f"❌ BLE命令發送錯誤: {e}")
            self.logger.error(f"BLE命令發送錯誤: {e}")
            # 命令發送失敗不應該導致整個連接斷開
    
    async def send_text_to_lcd_async(self, original_text, translated_text):
        """異步發送文字到ESP32 LCD顯示"""
        try:
            if not self.connected or not self.client:
                return
            
            # 準備LCD顯示數據包
            # 格式: 'L' + 原文長度(2字節小端序) + 翻譯長度(2字節小端序) + 原文 + 翻譯
            original_bytes = original_text.encode('utf-8')[:50]  # 限制長度
            translated_bytes = translated_text.encode('utf-8')[:50]
            
            print(f"📝 準備發送LCD文字: 原文='{original_text}' ({len(original_bytes)}字節), 翻譯='{translated_text}' ({len(translated_bytes)}字節)")
            
            data_packet = (b'L' + 
                          struct.pack('<H', len(original_bytes)) +    # 小端序2字節
                          struct.pack('<H', len(translated_bytes)) +  # 小端序2字節
                          original_bytes + translated_bytes)
            
            print(f"📦 LCD數據包總長度: {len(data_packet)} 字節")
            
            # 分塊發送文字數據 (BLE限制20字節)
            chunk_size = 20
            for i in range(0, len(data_packet), chunk_size):
                chunk = data_packet[i:i + chunk_size]
                await self.client.write_gatt_char(self.command_char_uuid, chunk)
                await asyncio.sleep(0.05)  # 增加延遲確保ESP32有時間處理
                print(f"📤 LCD數據塊 {i//chunk_size + 1}: {len(chunk)} 字節")
            
            print(f"✨ LCD文字發送完成")
            
        except Exception as e:
            self.logger.error(f"LCD文字發送錯誤: {e}")
    
    def send_text_to_lcd(self, original_text, translated_text):
        """發送文字到ESP32 LCD顯示 (同步包裝器)"""
        try:
            if self.connected and self.client:
                self._run_async_task(self.send_text_to_lcd_async(original_text, translated_text), timeout=5)
        except Exception as e:
            self.logger.error(f"發送LCD文字錯誤: {e}")
    
    def send_command(self, command):
        """發送命令到ESP32 (同步包裝器)"""
        try:
            if self.connected and self.client:
                self._run_async_task(self.send_command_async(command), timeout=5)
        except Exception as e:
            self.logger.error(f"發送命令錯誤: {e}")
    
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
        try:
            if self.connected and self.client:
                self._run_async_task(self.send_status_async(), timeout=5)
        except Exception as e:
            self.logger.error(f"發送狀態錯誤: {e}")
    
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
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """設置信號處理器來優雅地關閉程序"""
        def signal_handler(signum, frame):
            print(f"\n🛑 接收到信號 {signum}，正在優雅地關閉程序...")
            self.running = False
        
        # 註冊信號處理器
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # 終止信號
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, signal_handler)  # 掛起信號
    
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
        devices = self.bluetooth_handler.scan_devices()
        
        if not devices:
            print("❌ 未找到任何設備")
            # 手動輸入地址
            device_address = input("請輸入ESP32設備地址 (例: XX:XX:XX:XX:XX:XX): ").strip()
            if device_address:
                return self.bluetooth_handler.connect(device_address)
            return False
        
        # 讓用戶選擇設備
        while True:
            try:
                print(f"\n選項:")
                print(f"  1-{len(devices)}: 選擇設備")
                print(f"  r: 重新掃描")
                print(f"  q: 退出")
                
                choice = input(f"\n請選擇 [1-{len(devices)}/r/q]: ").strip().lower()
                
                if choice == 'q':
                    print("👋 用戶取消連接")
                    return False
                elif choice == 'r':
                    print("🔄 重新掃描設備...")
                    devices = self.bluetooth_handler.scan_devices()
                    if not devices:
                        print("❌ 重新掃描後仍未找到設備")
                        continue
                    continue
                elif not choice:
                    print("❌ 請輸入有效的選擇")
                    continue
                
                try:
                    index = int(choice) - 1
                    if 0 <= index < len(devices):
                        selected_device = devices[index]
                        device_name = getattr(selected_device, 'name', 'Unknown') or 'Unknown'
                        device_address = getattr(selected_device, 'address', 'Unknown')
                        
                        print(f"✅ 選擇設備: {device_name} ({device_address})")
                        
                        # 嘗試連接
                        if hasattr(selected_device, 'address'):
                            if self.bluetooth_handler.connect(selected_device.address):
                                return True
                            else:
                                print("❌ 連接失敗，請重試")
                                continue
                        else:
                            print("❌ 設備信息無效，請選擇其他設備")
                            continue
                    else:
                        print(f"❌ 請輸入 1-{len(devices)} 之間的數字")
                        continue
                except ValueError:
                    print("❌ 請輸入有效的數字")
                    continue
                except Exception as e:
                    print(f"❌ 選擇設備時發生錯誤: {e}")
                    continue
                    
            except KeyboardInterrupt:
                print("\n👋 用戶取消連接")
                return False
        
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
            
            print("\n" + "🎉" * 20)
            print("✅ ESP32 AI語音翻譯系統已就緒！")
            print("🎉" * 20)
            print("\n📋 使用說明:")
            print("  🎤 手動模式: 按下ESP32的GPIO2按鈕 → 開始15秒錄音")
            print("  ⚡ 即時模式: 系統持續監聽，檢測到語音自動開始3秒片段處理")
            print("  🤖 邊講邊譯: 語音識別 → AI翻譯 → 語音合成 → 即時播放")
            print("  📺 翻譯結果會同時顯示在Terminal和ESP32 LCD上")
            print("  📝 所有逐字稿和翻譯都會記錄到日誌文件中")
            print("\n⚡ 即時監聽模式已啟動，開始說話即可...")
            print("   (按 Ctrl+C 退出程序)")
            print("=" * 70)
            
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
        
        try:
            # 先設置停止標誌
            if hasattr(self.bluetooth_handler, 'should_stop'):
                self.bluetooth_handler.should_stop = True
            
            # 安全地斷開藍牙連接
            if self.bluetooth_handler:
                self.bluetooth_handler.disconnect()
                
                # 安全關閉事件循環
                self.bluetooth_handler.safe_shutdown()
            
            # 等待一段時間讓清理完成
            time.sleep(2)
            
            print("✅ 系統已安全關閉")
            
        except Exception as e:
            print(f"⚠️ 關閉時發生錯誤: {e}")
            print("✅ 系統已強制關閉")


if __name__ == "__main__":
    app = ESP32VoiceMicrophoneApp()
    app.run()
