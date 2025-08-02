import pyaudio
import wave
import threading
import time
import queue
from collections import deque
import numpy as np
import torch
import scipy.io.wavfile
import tempfile
import os
import pygame
import google.generativeai as genai
from OpenVoice.checkpoints_v2.MeloTTS.melo.api import TTS
from OpenVoice.openvoice.api import ToneColorConverter
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
import glob
import asyncio
import concurrent.futures

# 在程序開始時就禁用MPS以避免設備分配問題
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
if torch.backends.mps.is_available():
    torch.backends.mps.is_available = lambda: False
    print("⚠️ 已全局禁用MPS設備以避免兼容性問題")

class RealtimeVoiceTranslator:
    def __init__(self):
        # 系統配置
        # 強制使用CPU避免MacOS MPS設備問題
        self.device = "cpu"
        self.rate = 16000
        self.chunk = 512  # 更小的chunk以減少延遲
        self.format = pyaudio.paInt16
        self.channels = 1
        
        # 即時處理參數 - 極端優化為3秒以內
        self.silence_threshold = 200  # 進一步降低閾值
        self.silence_duration = 0.2   # 縮短到0.2秒
        self.min_speech_duration = 0.1  # 最短語音長度
        self.max_segment_duration = 2.0  # 更短的語音段
        
        # 系統狀態
        self.is_active = False
        self.should_stop = False
        self.gemini_api_key = None
        self.model = None
        
        # OpenVoice模型
        self.tone_color_converter = None
        self.tts_models = {}
        self.target_se = None
        self.cloned_voice_path = None
        
        # 語言設置
        self.source_language = 'zh'
        self.target_language = 'en'
        self.supported_languages = {
            'zh': '中文', 'en': '英文', 'ja': '日文', 'ko': '韓文',
            'es': '西班牙文', 'fr': '法文'
        }
        self.openvoice_language_map = {
            'zh': 'ZH', 'en': 'EN_NEWEST', 'ja': 'JP', 
            'ko': 'KR', 'es': 'ES', 'fr': 'FR'
        }
        
        # 處理隊列 - 使用更小的隊列以減少延遲
        self.audio_queue = queue.Queue(maxsize=5)
        self.transcription_queue = queue.Queue(maxsize=3)
        self.synthesis_queue = queue.Queue(maxsize=3)
        self.playback_queue = queue.Queue(maxsize=2)
        
        # 統計信息
        self.processing_times = deque(maxlen=10)
        
        # GUI
        self.gui = None
        
        # 執行緒池
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        
        # 初始化pygame
        pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
        
        print("🚀 超低延遲即時語音翻譯系統初始化完成")
    
    def setup_api(self, api_key):
        """設置API"""
        try:
            self.gemini_api_key = api_key
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
            # 測試API
            test_response = self.model.generate_content("test")
            print("✅ Gemini API 設置成功")
            return True
        except Exception as e:
            print(f"❌ API 設置失敗: {e}")
            return False
    
    def load_models(self):
        """預載入所有模型以減少延遲"""
        try:
            print("🔄 預載入模型中...")
            start_time = time.time()
            
            # 載入ToneColorConverter
            ckpt_converter = 'OpenVoice/checkpoints_v2/converter'
            self.tone_color_converter = ToneColorConverter(
                f'{ckpt_converter}/config.json', 
                device=self.device
            )
            self.tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')
            
            # 預載入常用語言的TTS模型
            for lang in ['EN_NEWEST', 'ZH', 'JP']:
                try:
                    self.tts_models[lang] = TTS(language=lang, device=self.device)
                    print(f"✅ {lang} TTS模型載入完成")
                except Exception as e:
                    print(f"⚠️ {lang} TTS模型載入失敗: {e}")
            
            # 如果有現存語音文件，載入特徵
            if os.path.exists("cloned_voices"):
                voice_files = glob.glob("cloned_voices/*.wav")
                if voice_files:
                    self.cloned_voice_path = voice_files[0]
                    try:
                        self.target_se = self.tone_color_converter.extract_se(self.cloned_voice_path)
                        # 強制將特徵移到CPU
                        if hasattr(self.target_se, 'cpu'):
                            self.target_se = self.target_se.cpu()
                        print("✅ 語音特徵載入完成")
                    except Exception as e:
                        print(f"⚠️ 語音特徵載入錯誤: {e}")
            
            load_time = time.time() - start_time
            print(f"✅ 所有模型載入完成，耗時: {load_time:.2f}秒")
            return True
            
        except Exception as e:
            print(f"❌ 模型載入失敗: {e}")
            return False
    
    def clone_voice(self, duration=3):
        """快速語音克隆"""
        try:
            print("🎤 開始快速語音錄製...")
            
            if not os.path.exists("cloned_voices"):
                os.makedirs("cloned_voices")
            
            # 錄音
            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            
            frames = []
            start_time = time.time()
            
            print("🎙️ 請開始說話...")
            while time.time() - start_time < duration:
                data = stream.read(self.chunk)
                frames.append(data)
            
            stream.stop_stream()
            stream.close()
            audio.terminate()
            
            # 保存錄音
            clone_file = f"cloned_voices/voice_clone_{int(time.time())}.wav"
            wf = wave.open(clone_file, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(pyaudio.PyAudio().get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(frames))
            wf.close()
            
            # 提取特徵
            if self.tone_color_converter:
                try:
                    # 確保特徵提取在CPU上進行
                    self.target_se = self.tone_color_converter.extract_se(clone_file)
                    # 強制將特徵移到CPU
                    if hasattr(self.target_se, 'cpu'):
                        self.target_se = self.target_se.cpu()
                    self.cloned_voice_path = clone_file
                    print("✅ 語音克隆完成")
                    return True
                except Exception as e:
                    print(f"⚠️ 語音特徵提取錯誤: {e}")
                    return False
            
        except Exception as e:
            print(f"❌ 語音克隆失敗: {e}")
            return False
    
    def start_realtime_translation(self):
        """啟動超低延遲即時翻譯"""
        if not self.model or not self.tone_color_converter:
            print("❌ 請先設置API和載入模型")
            return False
        
        self.is_active = True
        self.should_stop = False
        
        # 清空隊列
        self._clear_queues()
        
        # 啟動處理線程
        threads = [
            threading.Thread(target=self._audio_capture_worker, daemon=True),
            threading.Thread(target=self._transcription_worker, daemon=True),
            threading.Thread(target=self._synthesis_worker, daemon=True),
            threading.Thread(target=self._playback_worker, daemon=True),
        ]
        
        for thread in threads:
            thread.start()
        
        self.threads = threads
        print("🎤 即時翻譯已啟動 - 目標延遲 < 3秒")
        return True
    
    def stop_realtime_translation(self):
        """停止即時翻譯"""
        self.should_stop = True
        self.is_active = False
        
        # 等待線程結束
        if hasattr(self, 'threads'):
            for thread in self.threads:
                thread.join(timeout=2)
        
        # 清空隊列
        self._clear_queues()
        print("⏹️ 即時翻譯已停止")
    
    def _clear_queues(self):
        """清空所有隊列"""
        queues = [self.audio_queue, self.transcription_queue, 
                 self.synthesis_queue, self.playback_queue]
        for q in queues:
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
    
    def _audio_capture_worker(self):
        """音頻捕獲線程 - 優化為流式處理"""
        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        current_segment = []
        last_speech_time = 0
        is_speech_detected = False
        segment_start_time = time.time()
        
        print("🎤 音頻捕獲啟動")
        
        while self.is_active and not self.should_stop:
            try:
                data = stream.read(self.chunk, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16)
                
                # 計算音量
                rms = np.sqrt(np.mean(audio_np.astype(np.float64)**2))
                current_time = time.time()
                
                # 語音活動檢測
                if rms > self.silence_threshold:
                    if not is_speech_detected:
                        is_speech_detected = True
                        segment_start_time = current_time
                        if self.gui:
                            self.gui.update_status("🎤 檢測到語音...")
                    
                    current_segment.extend(audio_np)
                    last_speech_time = current_time
                
                else:
                    if is_speech_detected:
                        silence_duration = current_time - last_speech_time
                        segment_duration = current_time - segment_start_time
                        
                        # 條件判斷：靜音超時 或 語音段過長
                        should_process = (
                            silence_duration >= self.silence_duration or 
                            segment_duration >= self.max_segment_duration
                        )
                        
                        if should_process and len(current_segment) > int(self.rate * self.min_speech_duration):
                            # 發送音頻段處理
                            audio_data = np.array(current_segment, dtype=np.int16)
                            try:
                                self.audio_queue.put_nowait((audio_data, time.time()))
                                if self.gui:
                                    self.gui.update_status("🔄 處理語音...")
                            except queue.Full:
                                print("⚠️ 音頻隊列滿，跳過此段")
                            
                            current_segment = []
                            is_speech_detected = False
                
            except Exception as e:
                print(f"❌ 音頻捕獲錯誤: {e}")
                break
        
        stream.stop_stream()
        stream.close()
        audio.terminate()
        print("🎤 音頻捕獲停止")
    
    def _transcription_worker(self):
        """轉錄和翻譯線程 - 合併處理以減少延遲"""
        print("📝 轉錄翻譯線程啟動")
        
        while self.is_active or not self.audio_queue.empty():
            try:
                audio_data, capture_time = self.audio_queue.get(timeout=1)
                process_start = time.time()
                
                # 保存臨時音頻文件
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                scipy.io.wavfile.write(temp_file.name, self.rate, audio_data)
                
                # 上傳音頻到Gemini
                audio_file = genai.upload_file(path=temp_file.name)
                
                # 合併轉錄和翻譯為一次API調用以減少延遲
                source_lang = self.supported_languages[self.source_language]
                target_lang = self.supported_languages[self.target_language]
                
                if self.source_language == self.target_language:
                    prompt = f"請將這段音頻中的{source_lang}語音內容轉換為文字。只回傳轉錄的文字內容。"
                    response = self.model.generate_content([audio_file, prompt])
                    original_text = response.text.strip()
                    translated_text = original_text
                else:
                    # 一次性完成轉錄和翻譯
                    prompt = f"""請執行以下兩個步驟：
1. 將音頻中的{source_lang}語音轉換為文字
2. 將轉錄結果翻譯為{target_lang}

請用以下格式回應：
原文：[轉錄結果]
翻譯：[翻譯結果]"""
                    
                    response = self.model.generate_content([audio_file, prompt])
                    result = response.text.strip()
                    
                    # 解析結果
                    lines = result.split('\n')
                    original_text = ""
                    translated_text = ""
                    
                    for line in lines:
                        if line.startswith('原文：'):
                            original_text = line[3:].strip()
                        elif line.startswith('翻譯：'):
                            translated_text = line[3:].strip()
                    
                    # 如果解析失敗，使用整個回應作為翻譯
                    if not translated_text:
                        translated_text = result
                        original_text = "解析失敗"
                
                # 清理文件
                genai.delete_file(audio_file.name)
                os.unlink(temp_file.name)
                
                process_time = time.time() - process_start
                total_latency = time.time() - capture_time
                
                print(f"📝 轉錄: {original_text}")
                print(f"🌍 翻譯: {translated_text}")
                print(f"⏱️ 處理時間: {process_time:.2f}s, 總延遲: {total_latency:.2f}s")
                
                # 更新GUI
                if self.gui:
                    self.gui.add_text(original_text, translated_text)
                
                # 發送到語音合成
                if translated_text.strip():
                    try:
                        self.transcription_queue.put_nowait((translated_text, capture_time))
                    except queue.Full:
                        print("⚠️ 轉錄隊列滿，跳過合成")
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 轉錄翻譯錯誤: {e}")
        
        print("📝 轉錄翻譯線程停止")
    
    def _synthesis_worker(self):
        """語音合成線程 - 使用預載入模型"""
        print("🔊 語音合成線程啟動")
        
        while self.is_active or not self.transcription_queue.empty():
            try:
                text, capture_time = self.transcription_queue.get(timeout=1)
                
                if self.target_se is None:
                    print("⚠️ 無語音特徵，跳過合成")
                    continue
                
                synthesis_start = time.time()
                
                # 獲取目標語言的TTS模型
                target_lang_key = self.openvoice_language_map.get(self.target_language, 'EN_NEWEST')
                
                if target_lang_key not in self.tts_models:
                    print(f"⚠️ {target_lang_key} TTS模型未載入")
                    continue
                
                tts_model = self.tts_models[target_lang_key]
                
                # 生成基礎語音
                temp_src = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                speaker_ids = tts_model.hps.data.spk2id
                speaker_key = list(speaker_ids.keys())[0]
                speaker_id = speaker_ids[speaker_key]
                
                # 使用更快的設置，確保在CPU上執行
                try:
                    # 確保模型在CPU上
                    if hasattr(tts_model, 'model'):
                        tts_model.model = tts_model.model.cpu()
                    
                    tts_model.tts_to_file(text, speaker_id, temp_src.name, speed=1.1, quiet=True)
                except Exception as e:
                    print(f"⚠️ TTS合成錯誤: {e}")
                    # 嘗試重新載入模型並強制使用CPU
                    try:
                        del self.tts_models[target_lang_key]
                        self.tts_models[target_lang_key] = TTS(language=target_lang_key, device="cpu")
                        tts_model = self.tts_models[target_lang_key]
                        tts_model.tts_to_file(text, speaker_id, temp_src.name, speed=1.1, quiet=True)
                        print("✅ 重新載入TTS模型成功")
                    except Exception as e2:
                        print(f"❌ 重新載入TTS模型失敗: {e2}")
                        os.unlink(temp_src.name)
                        continue
                
                # 語音轉換
                speaker_key_formatted = speaker_key.lower().replace('_', '-')
                source_se_path = f'OpenVoice/checkpoints_v2/base_speakers/ses/{speaker_key_formatted}.pth'
                
                if os.path.exists(source_se_path):
                    # 強制載入到CPU並確保張量設備一致
                    source_se = torch.load(source_se_path, map_location="cpu")
                    
                    # 確保target_se也在CPU上
                    if self.target_se is not None:
                        if hasattr(self.target_se, 'cpu'):
                            target_se_cpu = self.target_se.cpu()
                        else:
                            target_se_cpu = self.target_se
                    else:
                        target_se_cpu = self.target_se
                    
                    output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                    
                    try:
                        self.tone_color_converter.convert(
                            audio_src_path=temp_src.name,
                            src_se=source_se,
                            tgt_se=target_se_cpu,
                            output_path=output_file.name,
                            message="@RealTime"
                        )
                    except Exception as conv_error:
                        print(f"⚠️ 語音轉換錯誤: {conv_error}")
                        # 如果轉換失敗，使用原始TTS輸出
                        import shutil
                        shutil.copy2(temp_src.name, output_file.name)
                    
                    synthesis_time = time.time() - synthesis_start
                    total_latency = time.time() - capture_time
                    
                    print(f"🔊 合成完成，耗時: {synthesis_time:.2f}s, 總延遲: {total_latency:.2f}s")
                    
                    # 發送到播放隊列
                    try:
                        self.synthesis_queue.put_nowait((output_file.name, capture_time))
                    except queue.Full:
                        os.unlink(output_file.name)
                        print("⚠️ 合成隊列滿，跳過播放")
                else:
                    print(f"⚠️ 源語音特徵文件不存在: {source_se_path}")
                
                # 清理臨時文件
                os.unlink(temp_src.name)
                self.transcription_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 語音合成錯誤: {e}")
        
        print("🔊 語音合成線程停止")
    
    def _playback_worker(self):
        """音頻播放線程"""
        print("🔈 音頻播放線程啟動")
        
        while self.is_active or not self.synthesis_queue.empty():
            try:
                audio_file, capture_time = self.synthesis_queue.get(timeout=1)
                
                # 播放音頻
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()
                
                total_latency = time.time() - capture_time
                self.processing_times.append(total_latency)
                
                avg_latency = sum(self.processing_times) / len(self.processing_times)
                print(f"🔈 播放開始，總延遲: {total_latency:.2f}s, 平均: {avg_latency:.2f}s")
                
                if self.gui:
                    self.gui.update_latency(total_latency, avg_latency)
                
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    if self.should_stop:
                        pygame.mixer.music.stop()
                        break
                
                # 清理文件
                try:
                    os.unlink(audio_file)
                except:
                    pass
                
                self.synthesis_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 音頻播放錯誤: {e}")
        
        print("🔈 音頻播放線程停止")

class RealtimeTranslatorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚡ 超低延遲即時語音翻譯系統")
        self.root.geometry("1000x700")
        self.root.configure(bg='#1a1a1a')
        
        self.translator = RealtimeVoiceTranslator()
        self.translator.gui = self
        
        self.is_active = False
        self.create_widgets()
    
    def create_widgets(self):
        # 標題
        title_frame = tk.Frame(self.root, bg='#1a1a1a')
        title_frame.pack(pady=10)
        
        tk.Label(title_frame, text="⚡ 超低延遲即時語音翻譯", 
                font=('Arial', 20, 'bold'), 
                bg='#1a1a1a', fg='#00ff00').pack()
        
        tk.Label(title_frame, text="目標延遲 < 3秒", 
                font=('Arial', 12), 
                bg='#1a1a1a', fg='#ffff00').pack()
        
        # API設置
        api_frame = tk.LabelFrame(self.root, text="API設置", 
                                 bg='#2a2a2a', fg='white', font=('Arial', 12, 'bold'))
        api_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Label(api_frame, text="Gemini API Key:", 
                bg='#2a2a2a', fg='white').grid(row=0, column=0, sticky='w', padx=5)
        
        self.api_entry = tk.Entry(api_frame, width=50, show='*')
        self.api_entry.grid(row=0, column=1, padx=5)
        
        tk.Button(api_frame, text="設置API", command=self.setup_api,
                 bg='#4a4a4a', fg='white').grid(row=0, column=2, padx=5)
        
        # 語言設置
        lang_frame = tk.LabelFrame(self.root, text="語言設置", 
                                  bg='#2a2a2a', fg='white', font=('Arial', 12, 'bold'))
        lang_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Label(lang_frame, text="原始語言:", 
                bg='#2a2a2a', fg='white').grid(row=0, column=0, padx=5)
        
        self.source_var = tk.StringVar(value='zh')
        source_combo = ttk.Combobox(lang_frame, textvariable=self.source_var,
                                   values=list(self.translator.supported_languages.keys()),
                                   state='readonly', width=10)
        source_combo.grid(row=0, column=1, padx=5)
        
        tk.Label(lang_frame, text="目標語言:", 
                bg='#2a2a2a', fg='white').grid(row=0, column=2, padx=5)
        
        self.target_var = tk.StringVar(value='en')
        target_combo = ttk.Combobox(lang_frame, textvariable=self.target_var,
                                   values=list(self.translator.supported_languages.keys()),
                                   state='readonly', width=10)
        target_combo.grid(row=0, column=3, padx=5)
        
        # 控制按鈕
        control_frame = tk.Frame(self.root, bg='#1a1a1a')
        control_frame.pack(pady=10)
        
        tk.Button(control_frame, text="載入模型", command=self.load_models,
                 bg='#4a4a4a', fg='white', font=('Arial', 12)).pack(side='left', padx=5)
        
        tk.Button(control_frame, text="錄製語音", command=self.clone_voice,
                 bg='#4a4a4a', fg='white', font=('Arial', 12)).pack(side='left', padx=5)
        
        self.start_button = tk.Button(control_frame, text="開始翻譯", command=self.toggle_translation,
                                     bg='#006600', fg='white', font=('Arial', 14, 'bold'))
        self.start_button.pack(side='left', padx=10)
        
        # 狀態顯示
        status_frame = tk.Frame(self.root, bg='#1a1a1a')
        status_frame.pack(fill='x', padx=10)
        
        self.status_label = tk.Label(status_frame, text="系統就緒", 
                                    bg='#1a1a1a', fg='#00ff00', font=('Arial', 12))
        self.status_label.pack(side='left')
        
        self.latency_label = tk.Label(status_frame, text="延遲: --", 
                                     bg='#1a1a1a', fg='#ffff00', font=('Arial', 12))
        self.latency_label.pack(side='right')
        
        # 文字顯示區域
        text_frame = tk.Frame(self.root, bg='#1a1a1a')
        text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # 原文顯示
        tk.Label(text_frame, text="原文：", bg='#1a1a1a', fg='white', 
                font=('Arial', 12, 'bold')).pack(anchor='w')
        
        self.original_text = scrolledtext.ScrolledText(text_frame, height=8, 
                                                      bg='#2a2a2a', fg='white',
                                                      font=('Arial', 11))
        self.original_text.pack(fill='both', expand=True, pady=(0, 10))
        
        # 翻譯顯示
        tk.Label(text_frame, text="翻譯：", bg='#1a1a1a', fg='white', 
                font=('Arial', 12, 'bold')).pack(anchor='w')
        
        self.translated_text = scrolledtext.ScrolledText(text_frame, height=8, 
                                                        bg='#2a2a2a', fg='#00ff00',
                                                        font=('Arial', 11))
        self.translated_text.pack(fill='both', expand=True)
    
    def setup_api(self):
        api_key = self.api_entry.get().strip()
        if not api_key:
            messagebox.showerror("錯誤", "請輸入API Key")
            return
        
        if self.translator.setup_api(api_key):
            messagebox.showinfo("成功", "API設置成功")
            self.update_status("API已設置")
        else:
            messagebox.showerror("錯誤", "API設置失敗")
    
    def load_models(self):
        self.update_status("載入模型中...")
        
        def load_in_thread():
            success = self.translator.load_models()
            self.root.after(0, lambda: self.model_loaded(success))
        
        threading.Thread(target=load_in_thread, daemon=True).start()
    
    def model_loaded(self, success):
        if success:
            self.update_status("模型載入完成")
            messagebox.showinfo("成功", "模型載入完成")
        else:
            self.update_status("模型載入失敗")
            messagebox.showerror("錯誤", "模型載入失敗")
    
    def clone_voice(self):
        if not self.translator.tone_color_converter:
            messagebox.showerror("錯誤", "請先載入模型")
            return
        
        self.update_status("語音錄製中...")
        
        def clone_in_thread():
            success = self.translator.clone_voice()
            self.root.after(0, lambda: self.voice_cloned(success))
        
        threading.Thread(target=clone_in_thread, daemon=True).start()
    
    def voice_cloned(self, success):
        if success:
            self.update_status("語音克隆完成")
            messagebox.showinfo("成功", "語音克隆完成")
        else:
            self.update_status("語音克隆失敗")
            messagebox.showerror("錯誤", "語音克隆失敗")
    
    def toggle_translation(self):
        if not self.is_active:
            # 檢查準備狀態
            if not self.translator.model:
                messagebox.showerror("錯誤", "請先設置API")
                return
            
            if not self.translator.tone_color_converter:
                messagebox.showerror("錯誤", "請先載入模型")
                return
            
            if self.translator.target_se is None:
                messagebox.showerror("錯誤", "請先錄製語音")
                return
            
            # 設置語言
            self.translator.source_language = self.source_var.get()
            self.translator.target_language = self.target_var.get()
            
            # 清空文字區域
            self.original_text.delete(1.0, tk.END)
            self.translated_text.delete(1.0, tk.END)
            
            # 啟動翻譯
            if self.translator.start_realtime_translation():
                self.is_active = True
                self.start_button.config(text="停止翻譯", bg='#cc0000')
                self.update_status("即時翻譯啟動")
        else:
            # 停止翻譯
            self.translator.stop_realtime_translation()
            self.is_active = False
            self.start_button.config(text="開始翻譯", bg='#006600')
            self.update_status("翻譯已停止")
    
    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()
    
    def update_latency(self, current, average):
        color = '#00ff00' if current < 3.0 else '#ffff00' if current < 5.0 else '#ff0000'
        self.latency_label.config(
            text=f"延遲: {current:.1f}s (平均: {average:.1f}s)",
            fg=color
        )
    
    def add_text(self, original, translated):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        self.original_text.insert(tk.END, f"[{timestamp}] {original}\n")
        self.original_text.see(tk.END)
        
        self.translated_text.insert(tk.END, f"[{timestamp}] {translated}\n")
        self.translated_text.see(tk.END)
    
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def on_closing(self):
        if self.is_active:
            self.translator.stop_realtime_translation()
        self.root.destroy()

if __name__ == "__main__":
    app = RealtimeTranslatorGUI()
    app.run()