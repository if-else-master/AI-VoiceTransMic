#!/usr/bin/env python3
"""
超快速即時語音翻譯系統
目標：延遲 < 3秒
策略：簡化流程，快速響應
"""

import pyaudio
import wave
import threading
import time
import queue
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

class UltraFastTranslator:
    def __init__(self):
        print("⚡ 初始化超快速翻譯系統...")
        
        # 基本配置
        self.device = "cpu"  # 強制CPU避免設備問題
        self.rate = 16000
        self.chunk = 256  # 極小chunk
        self.format = pyaudio.paInt16
        self.channels = 1
        
        # 超激進的延遲優化
        self.silence_threshold = 150
        self.silence_duration = 0.15  # 極短靜音檢測
        self.min_speech_duration = 0.05
        self.max_segment_duration = 1.5  # 強制短語音段
        
        # API
        self.gemini_api_key = None
        self.model = None
        
        # OpenVoice - 只載入必要模型
        self.tone_color_converter = None
        self.en_tts_model = None  # 只載入英語模型
        self.target_se = None
        
        # 語言
        self.source_language = 'zh'
        self.target_language = 'en'
        
        # 控制
        self.is_active = False
        self.should_stop = False
        
        # 隊列 - 極小緩衝
        self.audio_queue = queue.Queue(maxsize=2)
        self.output_queue = queue.Queue(maxsize=2)
        
        # 統計
        self.latencies = []
        
        # GUI引用
        self.gui = None
        
        # 初始化pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
        
        print("✅ 超快速翻譯系統初始化完成")
    
    def setup_api(self, api_key):
        """設置API"""
        try:
            self.gemini_api_key = api_key
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
            # 預熱API
            self.model.generate_content("test")
            print("✅ Gemini API 預熱完成")
            return True
        except Exception as e:
            print(f"❌ API設置失敗: {e}")
            return False
    
    def quick_load_models(self):
        """快速載入關鍵模型"""
        try:
            print("🚀 快速載入模型...")
            start_time = time.time()
            
            # 1. 載入ToneColorConverter
            ckpt_converter = 'OpenVoice/checkpoints_v2/converter'
            self.tone_color_converter = ToneColorConverter(
                f'{ckpt_converter}/config.json', 
                device=self.device
            )
            self.tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')
            print("✅ ToneColorConverter載入完成")
            
            # 2. 只載入英語TTS模型（最快）
            self.en_tts_model = TTS(language='EN_NEWEST', device=self.device)
            print("✅ 英語TTS模型載入完成")
            
            # 3. 載入現有語音特徵
            import glob
            voice_files = glob.glob("cloned_voices/*.wav")
            if voice_files:
                self.target_se = self.tone_color_converter.extract_se(voice_files[0])
                print("✅ 語音特徵載入完成")
            
            load_time = time.time() - start_time
            print(f"✅ 模型載入完成，耗時: {load_time:.2f}秒")
            return True
            
        except Exception as e:
            print(f"❌ 模型載入失敗: {e}")
            return False
    
    def quick_clone_voice(self, duration=2):
        """快速語音克隆"""
        try:
            print("🎤 快速語音錄製（2秒）...")
            
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
            
            print("🎙️ 請說話...")
            while time.time() - start_time < duration:
                data = stream.read(self.chunk)
                frames.append(data)
            
            stream.stop_stream()
            stream.close()
            audio.terminate()
            
            # 保存
            clone_file = f"cloned_voices/fast_clone_{int(time.time())}.wav"
            wf = wave.open(clone_file, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(pyaudio.PyAudio().get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(frames))
            wf.close()
            
            # 快速提取特徵
            self.target_se = self.tone_color_converter.extract_se(clone_file)
            print("✅ 快速語音克隆完成")
            return True
            
        except Exception as e:
            print(f"❌ 語音克隆失敗: {e}")
            return False
    
    def start_ultra_fast_translation(self):
        """啟動超快速翻譯"""
        if not self.model or not self.tone_color_converter or self.target_se is None:
            print("❌ 系統未準備完成")
            return False
        
        self.is_active = True
        self.should_stop = False
        self.latencies = []
        
        # 清空隊列
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except: break
        while not self.output_queue.empty():
            try: self.output_queue.get_nowait()
            except: break
        
        # 啟動線程
        threads = [
            threading.Thread(target=self._ultra_fast_capture, daemon=True),
            threading.Thread(target=self._ultra_fast_process, daemon=True),
            threading.Thread(target=self._ultra_fast_play, daemon=True),
        ]
        
        for t in threads:
            t.start()
        
        self.threads = threads
        print("⚡ 超快速翻譯啟動 - 目標 < 3秒")
        return True
    
    def stop_translation(self):
        """停止翻譯"""
        self.should_stop = True
        self.is_active = False
        
        if hasattr(self, 'threads'):
            for t in self.threads:
                t.join(timeout=1)
        
        if self.latencies:
            avg_latency = sum(self.latencies) / len(self.latencies)
            print(f"📊 平均延遲: {avg_latency:.2f}秒")
        
        print("⏹️ 翻譯已停止")
    
    def _ultra_fast_capture(self):
        """超快音頻捕獲"""
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
        is_speech = False
        segment_start = time.time()
        
        print("🎤 超快音頻捕獲啟動")
        
        while self.is_active:
            try:
                data = stream.read(self.chunk, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_np.astype(np.float64)**2))
                current_time = time.time()
                
                if rms > self.silence_threshold:
                    if not is_speech:
                        is_speech = True
                        segment_start = current_time
                        if self.gui:
                            self.gui.update_status("🎤 語音...")
                    
                    current_segment.extend(audio_np)
                    last_speech_time = current_time
                
                else:
                    if is_speech:
                        silence_time = current_time - last_speech_time
                        segment_duration = current_time - segment_start
                        
                        # 更激進的分割條件
                        should_process = (
                            silence_time >= self.silence_duration or 
                            segment_duration >= self.max_segment_duration
                        )
                        
                        if should_process and len(current_segment) > int(self.rate * self.min_speech_duration):
                            audio_data = np.array(current_segment, dtype=np.int16)
                            try:
                                self.audio_queue.put_nowait((audio_data, current_time))
                                if self.gui:
                                    self.gui.update_status("🔄 處理中...")
                            except queue.Full:
                                pass  # 丟棄以避免延遲累積
                            
                            current_segment = []
                            is_speech = False
                
            except Exception as e:
                print(f"❌ 捕獲錯誤: {e}")
                break
        
        stream.stop_stream()
        stream.close()
        audio.terminate()
        print("🎤 音頻捕獲停止")
    
    def _ultra_fast_process(self):
        """超快處理流程"""
        print("⚡ 超快處理線程啟動")
        
        while self.is_active or not self.audio_queue.empty():
            try:
                audio_data, capture_time = self.audio_queue.get(timeout=0.5)
                process_start = time.time()
                
                # 1. 保存音頻
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                scipy.io.wavfile.write(temp_file.name, self.rate, audio_data)
                
                # 2. 上傳並處理（合併操作）
                audio_file = genai.upload_file(path=temp_file.name)
                
                # 3. 一次性轉錄+翻譯
                prompt = f"""處理這段中文語音，執行：
1. 轉錄為中文文字
2. 翻譯為英文
回傳格式：翻譯結果（不要包含其他文字）"""
                
                response = self.model.generate_content([audio_file, prompt])
                translated_text = response.text.strip()
                
                # 清理
                genai.delete_file(audio_file.name)
                os.unlink(temp_file.name)
                
                # 4. 快速語音合成
                output_file = self._ultra_fast_synthesize(translated_text)
                
                if output_file:
                    total_latency = time.time() - capture_time
                    self.latencies.append(total_latency)
                    
                    print(f"⚡ 翻譯: {translated_text}")
                    print(f"⏱️ 總延遲: {total_latency:.2f}秒")
                    
                    if self.gui:
                        self.gui.add_translation(translated_text, total_latency)
                    
                    try:
                        self.output_queue.put_nowait((output_file, total_latency))
                    except queue.Full:
                        try:
                            os.unlink(output_file)
                        except:
                            pass
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 處理錯誤: {e}")
        
        print("⚡ 處理線程停止")
    
    def _ultra_fast_synthesize(self, text):
        """超快語音合成"""
        try:
            if not text.strip() or len(text) > 200:  # 限制長度
                return None
            
            # 使用預載入的英語TTS模型
            temp_src = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            
            speaker_ids = self.en_tts_model.hps.data.spk2id
            speaker_key = list(speaker_ids.keys())[0]
            speaker_id = speaker_ids[speaker_key]
            
            # 快速TTS
            self.en_tts_model.tts_to_file(
                text, speaker_id, temp_src.name, 
                speed=1.2,  # 稍快語速
                quiet=True  # 靜默模式
            )
            
            # 快速語音轉換
            speaker_key_formatted = speaker_key.lower().replace('_', '-')
            source_se_path = f'OpenVoice/checkpoints_v2/base_speakers/ses/{speaker_key_formatted}.pth'
            
            if os.path.exists(source_se_path):
                source_se = torch.load(source_se_path, map_location=self.device)
                
                output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                self.tone_color_converter.convert(
                    audio_src_path=temp_src.name,
                    src_se=source_se,
                    tgt_se=self.target_se,
                    output_path=output_file.name,
                    message="@Fast"
                )
                
                os.unlink(temp_src.name)
                return output_file.name
            else:
                return temp_src.name  # 返回原始TTS結果
                
        except Exception as e:
            print(f"❌ 合成錯誤: {e}")
            return None
    
    def _ultra_fast_play(self):
        """超快播放"""
        print("🔊 超快播放線程啟動")
        
        while self.is_active or not self.output_queue.empty():
            try:
                audio_file, latency = self.output_queue.get(timeout=0.5)
                
                # 播放
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()
                
                # 不等待播放完成，立即處理下一個
                # 這樣可以重疊播放，進一步減少感知延遲
                
                print(f"🔊 播放開始，延遲: {latency:.2f}秒")
                
                # 清理文件
                def cleanup():
                    time.sleep(2)  # 等待播放完成
                    try:
                        os.unlink(audio_file)
                    except:
                        pass
                
                threading.Thread(target=cleanup, daemon=True).start()
                
                self.output_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 播放錯誤: {e}")
        
        print("🔊 播放線程停止")

class UltraFastGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚡ 超快速即時翻譯系統 (目標 < 3秒)")
        self.root.geometry("800x600")
        self.root.configure(bg='#000000')
        
        self.translator = UltraFastTranslator()
        self.translator.gui = self
        
        self.is_active = False
        self.create_widgets()
    
    def create_widgets(self):
        # 標題
        title_frame = tk.Frame(self.root, bg='#000000')
        title_frame.pack(pady=10)
        
        tk.Label(title_frame, text="⚡ 超快速即時翻譯", 
                font=('Arial', 24, 'bold'), 
                bg='#000000', fg='#00ff00').pack()
        
        tk.Label(title_frame, text="目標延遲 < 3秒", 
                font=('Arial', 14), 
                bg='#000000', fg='#ffff00').pack()
        
        # API設置
        api_frame = tk.Frame(self.root, bg='#000000')
        api_frame.pack(pady=10)
        
        tk.Label(api_frame, text="Gemini API Key:", 
                bg='#000000', fg='white', font=('Arial', 12)).pack(side='left')
        
        self.api_entry = tk.Entry(api_frame, width=40, show='*', font=('Arial', 12))
        self.api_entry.pack(side='left', padx=10)
        
        tk.Button(api_frame, text="設置", command=self.setup_api,
                 bg='#333333', fg='white', font=('Arial', 12)).pack(side='left')
        
        # 控制按鈕
        control_frame = tk.Frame(self.root, bg='#000000')
        control_frame.pack(pady=20)
        
        tk.Button(control_frame, text="快速載入模型", command=self.load_models,
                 bg='#333333', fg='white', font=('Arial', 14)).pack(side='left', padx=10)
        
        tk.Button(control_frame, text="快速錄音", command=self.clone_voice,
                 bg='#333333', fg='white', font=('Arial', 14)).pack(side='left', padx=10)
        
        self.start_button = tk.Button(control_frame, text="開始超快翻譯", command=self.toggle_translation,
                                     bg='#006600', fg='white', font=('Arial', 16, 'bold'))
        self.start_button.pack(side='left', padx=10)
        
        # 狀態
        self.status_label = tk.Label(self.root, text="系統就緒", 
                                    bg='#000000', fg='#00ff00', font=('Arial', 14))
        self.status_label.pack(pady=10)
        
        # 延遲顯示
        self.latency_label = tk.Label(self.root, text="延遲: --", 
                                     bg='#000000', fg='#ffff00', font=('Arial', 16, 'bold'))
        self.latency_label.pack()
        
        # 翻譯結果
        tk.Label(self.root, text="翻譯結果:", bg='#000000', fg='white', 
                font=('Arial', 14, 'bold')).pack(anchor='w', padx=20, pady=(20,5))
        
        self.result_text = scrolledtext.ScrolledText(self.root, height=15, 
                                                    bg='#111111', fg='#00ff00',
                                                    font=('Arial', 12))
        self.result_text.pack(fill='both', expand=True, padx=20, pady=10)
    
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
        self.update_status("快速載入模型中...")
        
        def load():
            success = self.translator.quick_load_models()
            self.root.after(0, lambda: self.model_loaded(success))
        
        threading.Thread(target=load, daemon=True).start()
    
    def model_loaded(self, success):
        if success:
            self.update_status("模型載入完成")
            messagebox.showinfo("成功", "模型快速載入完成")
        else:
            messagebox.showerror("錯誤", "模型載入失敗")
    
    def clone_voice(self):
        if not self.translator.tone_color_converter:
            messagebox.showerror("錯誤", "請先載入模型")
            return
        
        self.update_status("快速錄音中...")
        
        def clone():
            success = self.translator.quick_clone_voice()
            self.root.after(0, lambda: self.voice_cloned(success))
        
        threading.Thread(target=clone, daemon=True).start()
    
    def voice_cloned(self, success):
        if success:
            self.update_status("語音錄製完成")
            messagebox.showinfo("成功", "快速語音克隆完成")
        else:
            messagebox.showerror("錯誤", "語音克隆失敗")
    
    def toggle_translation(self):
        if not self.is_active:
            if not self.translator.model:
                messagebox.showerror("錯誤", "請先設置API")
                return
            if not self.translator.tone_color_converter:
                messagebox.showerror("錯誤", "請先載入模型")
                return
            if self.translator.target_se is None:
                messagebox.showerror("錯誤", "請先錄製語音")
                return
            
            self.result_text.delete(1.0, tk.END)
            
            if self.translator.start_ultra_fast_translation():
                self.is_active = True
                self.start_button.config(text="停止翻譯", bg='#cc0000')
                self.update_status("⚡ 超快翻譯運行中")
        else:
            self.translator.stop_translation()
            self.is_active = False
            self.start_button.config(text="開始超快翻譯", bg='#006600')
            self.update_status("翻譯已停止")
    
    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()
    
    def add_translation(self, text, latency):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = '#00ff00' if latency < 3.0 else '#ffff00' if latency < 5.0 else '#ff0000'
        
        self.result_text.insert(tk.END, f"[{timestamp}] {text}\n")
        self.result_text.see(tk.END)
        
        self.latency_label.config(text=f"延遲: {latency:.1f}秒", fg=color)
    
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def on_closing(self):
        if self.is_active:
            self.translator.stop_translation()
        self.root.destroy()

if __name__ == "__main__":
    app = UltraFastGUI()
    app.run()