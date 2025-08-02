# AI-VoiceTransMic


這是一個使用OpenVoice技術的即時語音翻譯系統，將原本使用XTTS-v2的demo.py功能移植為使用OpenVoice。

## 功能特色

- 🎤 即時語音錄製和識別
- 🌍 多語言翻譯支援（中、英、日、韓、西、法、德、意、葡）
- 🎭 語音克隆和音色轉換
- 🔊 即時語音合成輸出
- 💬 圖形化使用界面

## 系統要求

- Python 3.10+
- 已安裝OpenVoice及其依賴
- Gemini API Key（用於語音轉文字和翻譯）

## 安裝說明

1. 激活虛擬環境：
```bash
source .venv/bin/activate
```

2. 所有依賴已安裝完成（見requirements.txt）

## 使用方法

1. 運行主程序：
```bash
python openvoice_main.py
```

2. 在GUI中：
   - 輸入Gemini API Key並測試
   - 選擇原始語言和目標語言
   - 點擊"載入模型"載入OpenVoice模型
   - 點擊"錄製新語音"進行語音克隆
   - 點擊"開始即時翻譯"開始使用

## 主要改進

- 使用OpenVoice替代XTTS-v2進行語音合成
- 支援更多語言的語音克隆
- 改善的語音特徵提取和轉換
- 優化的音頻處理流程

## 文件說明

- `openvoice_main.py` - 主程序（OpenVoice版本）
- `demo.py` - 原始程序（XTTS版本）
- `new_main.py` - 原始OpenVoice示例
- `requirements.txt` - 所有依賴列表

## 注意事項

- 首次使用需要下載語言模型，可能需要較長時間
- 語音克隆功能需要先載入OpenVoice模型
- 建議在安靜環境中使用以獲得最佳效果