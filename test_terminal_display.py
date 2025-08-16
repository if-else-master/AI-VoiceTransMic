#!/usr/bin/env python3
"""
Terminal顯示功能測試腳本
測試逐字稿和翻譯的Terminal顯示效果
"""

from datetime import datetime
import time

def display_transcription_results(original_text, translated_text, process_time):
    """在Terminal中簡潔顯示逐字稿和翻譯結果"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # 簡潔的debug格式顯示
    print(f"\n[{timestamp}] 處理時間: {process_time:.1f}秒")
    print(f"原逐字稿：{original_text}")
    print(f"翻譯後的內容：{translated_text}")
    print("-" * 60)

def wrap_text(text, max_width):
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

def test_terminal_display():
    """測試Terminal顯示效果"""
    print("🧪 測試Terminal逐字稿顯示功能")
    print("=" * 50)
    
    # 測試案例1: 中文到英文
    original_text1 = "你好，我今天想要介紹一個很棒的AI語音翻譯系統，這個系統可以即時將語音轉換成文字，然後翻譯成不同的語言。"
    translated_text1 = "Hello, today I want to introduce a great AI voice translation system that can instantly convert speech to text and then translate it into different languages."
    
    display_transcription_results(original_text1, translated_text1, 2.3)
    
    time.sleep(2)
    
    # 測試案例2: 英文到中文
    original_text2 = "This is an amazing voice translation system powered by advanced AI technology. It can recognize speech, translate it, and even clone your voice for natural-sounding output."
    translated_text2 = "這是一個由先進AI技術驅動的驚人語音翻譯系統。它可以識別語音、翻譯語音，甚至可以克隆您的聲音以產生自然聲音的輸出。"
    
    display_transcription_results(original_text2, translated_text2, 1.8)
    
    time.sleep(2)
    
    # 測試案例3: 短文本
    original_text3 = "謝謝"
    translated_text3 = "Thank you"
    
    display_transcription_results(original_text3, translated_text3, 0.5)

if __name__ == "__main__":
    test_terminal_display()
