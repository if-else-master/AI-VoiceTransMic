/*
 * ESP32 AI語音翻譯麥克風系統 (簡化版)
 * 
 * 硬件配置:
 * - ESP32-WROOM-32
 * - INMP441 MEMS 麥克風
 * - 喇叭 (8Ω 0.5W)
 * 
 * 功能:
 * - 即時音頻捕獲
 * - 藍牙音頻傳輸
 * - 語音播放
 * 
 * 作者: Your Name
 * 版本: 1.3 (修復錄音判斷邏輯)
 * 日期: 2024
 * 
 * 修復說明:
 * - 兼容不同版本的ESP32 Arduino Core
 * - 修復LEDC函數API變更問題
 * - 修復錄音時間過短的判斷邏輯BUG
 * - 改善音頻樣本收集機制
 * - 降低錄音有效性判斷門檻
 */

#include <Arduino.h>
#include "BLEDevice.h"
#include "BLEServer.h"
#include "BLEUtils.h"
#include "BLE2902.h"
#include <driver/i2s.h>
#include <driver/dac.h>
#include <LiquidCrystal_I2C.h>  // ESP32 compatible version
#include <Wire.h>

// === 硬件配置 ===
// INMP441 麥克風引腳配置
#define I2S_WS 25     // LRCK (Left/Right Clock)
#define I2S_SD 33     // DOUT (Serial Data Out)  
#define I2S_SCK 32    // BCLK (Bit Clock)

// 喇叭 DAC 輸出
#define SPEAKER_PIN 26  // DAC 輸出引腳

// 控制按鈕
#define RECORD_BUTTON 2   // 錄音按鈕
#define MODE_BUTTON 4     // 模式切換按鈕

// LED 指示燈
#define LED_RECORDING 5   // 錄音指示燈
#define LED_PROCESSING 18 // 處理指示燈
#define LED_SPEAKING 19   // 播放指示燈

// LCD 顯示器配置
#define LCD_ADDRESS 0x27  // I2C地址
#define LCD_COLS 16       // 列數
#define LCD_ROWS 2        // 行數
#define LCD_SDA 21        // SDA引腳
#define LCD_SCL 22        // SCL引腳

// BLE配置
#define SERVICE_UUID        "12345678-1234-1234-1234-123456789abc"
#define AUDIO_CHAR_UUID     "87654321-4321-4321-4321-cba987654321"  
#define COMMAND_CHAR_UUID   "11111111-2222-3333-4444-555555555555"

// === 音頻參數 ===
#define SAMPLE_RATE 16000      // 採樣率 16kHz
#define BITS_PER_SAMPLE 16     // 16位音頻
#define CHANNELS 1             // 單聲道
#define BUFFER_SIZE 1024       // 緩衝區大小
#define MAX_AUDIO_DURATION 15  // 最大錄音時長（秒）
#define FIXED_RECORDING_DURATION 15  // 強制錄音時長（秒）
#define REALTIME_CHUNK_DURATION 3  // 即時處理的音頻片段長度（秒）

// === 全局變量 ===
BLEServer* pServer = nullptr;
BLECharacteristic* pAudioCharacteristic = nullptr;
BLECharacteristic* pCommandCharacteristic = nullptr;
LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLS, LCD_ROWS);

// 音頻緩衝區
int16_t audioBuffer[BUFFER_SIZE];
int16_t* recordingBuffer;
size_t bufferIndex = 0;
size_t maxBufferSize;

// 系統狀態
enum SystemState {
  IDLE,           // 空閒狀態
  RECORDING,      // 錄音中
  PROCESSING,     // 處理中
  PLAYING,        // 播放中
  BLUETOOTH_DISCONNECTED
};

SystemState currentState = BLUETOOTH_DISCONNECTED;
bool bluetoothConnected = false;
bool recordingActive = false;
unsigned long lastActivityTime = 0;
unsigned long recordingStartTime = 0;

// BLE連接狀態
bool deviceConnected = false;
bool oldDeviceConnected = false;

// 語音活動檢測
const int16_t SILENCE_THRESHOLD = 500;
const unsigned long SILENCE_DURATION = 1000;  // 1秒靜音
const unsigned long MIN_RECORDING_DURATION = 300; // 最短錄音300ms
unsigned long lastSpeechTime = 0;
bool speechDetected = false;

// 錄音模式控制
bool manualRecording = false;  // true: 按鈕觸發的手動錄音, false: 自動語音檢測錄音

// 函數聲明
void handleBLECommand(char command);
void startRecording(bool manual);
void playTestTone(int frequency, int duration_ms);
void playReceivedAudio(uint8_t* audioData, size_t audioSize);

// BLE服務器回調類
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("📱 BLE設備已連接");
    };

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("📱 BLE設備已斷開");
    }
};

// BLE特徵回調類
class MyCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
      String rxValue = pCharacteristic->getValue().c_str();

      if (rxValue.length() > 0) {
        char command = rxValue[0];
        handleBLECommand(command);
      }
    }
};

void setup() {
  Serial.begin(115200);
  Serial.println("🎤 ESP32 AI語音翻譯麥克風系統啟動中...");
  
  // 顯示初始內存狀態
  printMemoryInfo("系統啟動");
  
  // 初始化硬件
  initGPIO();
  printMemoryInfo("GPIO初始化後");
  
  initI2S();
  printMemoryInfo("I2S初始化後");
  
  initBLE();
  printMemoryInfo("BLE初始化後");
  
  initAudioBuffer();
  printMemoryInfo("音頻緩衝區初始化後");
  
  initLCD();
  printMemoryInfo("LCD初始化後");
  
  Serial.println("✅ 系統初始化完成！");
  Serial.println("📱 等待BLE連接...");
  currentState = BLUETOOTH_DISCONNECTED;
}

void loop() {
  // 檢查藍牙連接狀態
  checkBluetoothConnection();
  
  // 檢查按鈕輸入
  checkButtons();
  
  // 根據當前狀態執行相應操作
  switch (currentState) {
    case IDLE:
      handleIdleState();
      break;
      
    case RECORDING:
      handleRecordingState();
      break;
      
    case PROCESSING:
      handleProcessingState();
      break;
      
    case PLAYING:
      handlePlayingState();
      break;
      
    case BLUETOOTH_DISCONNECTED:
      handleDisconnectedState();
      break;
  }
  
  // 處理藍牙數據接收
  handleBluetoothData();
  
  delay(10); // 小延遲避免CPU過載
}

// === 初始化函數 ===

void initGPIO() {
  // 配置按鈕輸入
  pinMode(RECORD_BUTTON, INPUT_PULLUP);
  pinMode(MODE_BUTTON, INPUT_PULLUP);
  
  // 配置LED輸出
  pinMode(LED_RECORDING, OUTPUT);
  pinMode(LED_PROCESSING, OUTPUT);
  pinMode(LED_SPEAKING, OUTPUT);
  
  // 初始化LED狀態
  digitalWrite(LED_RECORDING, LOW);
  digitalWrite(LED_PROCESSING, LOW);
  digitalWrite(LED_SPEAKING, LOW);
  
  Serial.println("✅ GPIO 初始化完成");
}

void initI2S() {
  // I2S 配置 (麥克風輸入)
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = BUFFER_SIZE,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  
  // I2S 引腳配置
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  
  // 安裝 I2S 驅動
  esp_err_t result = i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  if (result != ESP_OK) {
    Serial.printf("❌ I2S 驅動安裝失敗: %d\n", result);
    return;
  }
  
  result = i2s_set_pin(I2S_NUM_0, &pin_config);
  if (result != ESP_OK) {
    Serial.printf("❌ I2S 引腳配置失敗: %d\n", result);
    return;
  }
  
  Serial.println("✅ I2S (麥克風) 初始化完成");
}

void initBLE() {
  // 初始化BLE設備
  BLEDevice::init("ESP32-VoiceMic");
  
  // 創建BLE服務器
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  
  // 創建BLE服務
  BLEService *pService = pServer->createService(SERVICE_UUID);
  
  // 創建音頻特徵 (用於發送音頻數據)
  pAudioCharacteristic = pService->createCharacteristic(
                      AUDIO_CHAR_UUID,
                      BLECharacteristic::PROPERTY_READ |
                      BLECharacteristic::PROPERTY_WRITE |
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pAudioCharacteristic->addDescriptor(new BLE2902());
  
  // 創建命令特徵 (用於接收控制命令)
  pCommandCharacteristic = pService->createCharacteristic(
                         COMMAND_CHAR_UUID,
                         BLECharacteristic::PROPERTY_READ |
                         BLECharacteristic::PROPERTY_WRITE
                       );
  pCommandCharacteristic->setCallbacks(new MyCallbacks());
  
  // 啟動服務
  pService->start();
  
  // 開始廣播
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(false);
  pAdvertising->setMinPreferred(0x0);
  BLEDevice::startAdvertising();
  
  Serial.println("✅ BLE初始化完成");
  Serial.println("📱 設備名稱: ESP32-VoiceMic");
  Serial.println("📡 等待BLE連接...");
}

void initAudioBuffer() {
  maxBufferSize = SAMPLE_RATE * MAX_AUDIO_DURATION;
  size_t requiredMemory = maxBufferSize * sizeof(int16_t);
  
  Serial.printf("🔍 嘗試分配音頻緩衝區: %d 樣本, %d 字節\n", maxBufferSize, requiredMemory);
  Serial.printf("📊 系統可用內存: %d 字節\n", ESP.getFreeHeap());
  
  // 檢查可用內存是否足夠
  if (ESP.getFreeHeap() < requiredMemory + 50000) { // 保留50KB安全邊界
    Serial.println("⚠️ 內存不足，減少緩衝區大小");
    
    // 計算可用的最大緩衝區大小
    size_t availableMemory = ESP.getFreeHeap() - 50000; // 保留安全邊界
    maxBufferSize = availableMemory / sizeof(int16_t);
    
    // 確保不超過10秒（作為後備）
    size_t maxSafeSize = SAMPLE_RATE * 10;
    if (maxBufferSize > maxSafeSize) {
      maxBufferSize = maxSafeSize;
    }
    
    Serial.printf("🔧 調整後緩衝區大小: %d 樣本 (%.1f秒)\n", 
                  maxBufferSize, (float)maxBufferSize / SAMPLE_RATE);
  }
  
  recordingBuffer = (int16_t*)malloc(maxBufferSize * sizeof(int16_t));
  
  if (recordingBuffer == NULL) {
    Serial.println("❌ 音頻緩衝區分配失敗");
    Serial.printf("❌ 嘗試分配: %d 字節, 可用內存: %d 字節\n", 
                  maxBufferSize * sizeof(int16_t), ESP.getFreeHeap());
    
    // 嘗試更小的緩衝區
    maxBufferSize = SAMPLE_RATE * 5; // 5秒作為最小緩衝區
    recordingBuffer = (int16_t*)malloc(maxBufferSize * sizeof(int16_t));
    
    if (recordingBuffer == NULL) {
      Serial.println("❌ 最小緩衝區分配也失敗，系統無法運行");
      return;
    } else {
      Serial.printf("✅ 使用最小緩衝區: %d 樣本 (5秒)\n", maxBufferSize);
    }
  } else {
    Serial.printf("✅ 音頻緩衝區分配成功: %d 樣本 (%.1f秒)\n", 
                  maxBufferSize, (float)maxBufferSize / SAMPLE_RATE);
    Serial.printf("📊 分配後剩餘內存: %d 字節\n", ESP.getFreeHeap());
  }
}

void initLCD() {
  // 初始化I2C
  Wire.begin(LCD_SDA, LCD_SCL);
  
  // 初始化LCD
  lcd.init();
  lcd.backlight();
  
  // 顯示啟動信息
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("ESP32-VoiceMic");
  lcd.setCursor(0, 1);
  lcd.print("Starting...");
  
  Serial.println("✅ LCD 初始化完成");
}

// === 狀態處理函數 ===

void handleIdleState() {
  // 持續的自動語音檢測 - 實現即時處理
  static unsigned long lastVoiceCheck = 0;
  
  if (millis() - lastVoiceCheck > 100) { // 每100ms檢查一次
    if (checkVoiceActivity()) {
      startRecording(false); // 自動模式
    }
    lastVoiceCheck = millis();
  }
  
  // 更新空閒顯示（減少頻率避免干擾）
  static unsigned long lastUpdate = 0;
  if (millis() - lastUpdate > 5000) { // 5秒更新一次
    Serial.println("📱 系統就緒，持續監聽中... - " + getCurrentTime());
    updateLCDDisplay("Listening", "Ready");
    lastUpdate = millis();
  }
}

void handleRecordingState() {
  unsigned long currentTime = millis();
  unsigned long elapsedTime = currentTime - recordingStartTime;
  
  // 計算實際可錄音的最大時長
  float maxRecordingTime = (float)maxBufferSize / SAMPLE_RATE;
  
  if (manualRecording) {
    // 按鈕觸發的手動錄音模式：使用實際可用的錄音時長
    float targetDuration = min((float)FIXED_RECORDING_DURATION, maxRecordingTime);
    
    if (elapsedTime >= targetDuration * 1000) {
      Serial.printf("⏰ 完成%.1f秒錄音，停止錄音\n", targetDuration);
      stopRecording();
      return;
    }
    
    // 繼續錄音並檢測語音活動（但不根據靜音停止）
    checkVoiceActivity();
    
    // 更新錄音顯示
    static unsigned long lastBlink = 0;
    if (currentTime - lastBlink > 500) {
      digitalWrite(LED_RECORDING, !digitalRead(LED_RECORDING));
      
      int duration = elapsedTime / 1000;
      int remaining = (int)targetDuration - duration;
      Serial.printf("🎤 手動錄音中... 已錄: %ds, 剩餘: %ds (最大%.1fs)\n", 
                    duration, remaining, maxRecordingTime);
      updateLCDDisplay("Manual Rec", String(duration) + "/" + String((int)targetDuration) + "s");
      lastBlink = currentTime;
    }
  } else {
    // 自動語音檢測錄音模式：使用短片段即時處理
    float realtimeChunkTime = min((float)REALTIME_CHUNK_DURATION, maxRecordingTime);
    
    // 檢查是否達到即時處理片段時長
    if (elapsedTime >= realtimeChunkTime * 1000) {
      Serial.printf("⚡ 達到即時處理片段時長(%.1fs)，發送處理\n", realtimeChunkTime);
      stopRecording();
      return;
    }
    
    // 檢查語音活動
    if (!checkVoiceActivity()) {
      // 檢查靜音時長
      if (currentTime - lastSpeechTime > SILENCE_DURATION) {
        // 修復：使用更合理的最短錄音時長判斷（100ms而不是300ms）
        if (elapsedTime > 100 && bufferIndex > 50) { // 至少100ms且有音頻樣本
          Serial.printf("🔇 檢測到靜音，發送即時處理 (時長:%dms, 樣本:%d)\n", elapsedTime, bufferIndex);
          stopRecording();
        } else {
          Serial.printf("🔇 檢測到靜音但錄音過短 (時長:%dms, 樣本:%d)，繼續等待\n", elapsedTime, bufferIndex);
        }
      }
    }
    
    // 更新錄音顯示
    static unsigned long lastBlink = 0;
    if (currentTime - lastBlink > 500) {
      digitalWrite(LED_RECORDING, !digitalRead(LED_RECORDING));
      
      int duration = elapsedTime / 1000;
      int remaining = (int)realtimeChunkTime - duration;
      Serial.printf("🎤 即時錄音中... 時長: %ds, 剩餘: %ds\n", duration, remaining);
      updateLCDDisplay("Live Rec", String(duration) + "/" + String((int)realtimeChunkTime) + "s");
      lastBlink = currentTime;
    }
  }
}

void handleProcessingState() {
  // 閃爍處理LED
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 300) {
    digitalWrite(LED_PROCESSING, !digitalRead(LED_PROCESSING));
    lastBlink = millis();
  }
  
  Serial.println("🔄 處理中... 請稍候");
  updateLCDDisplay("Processing", "Please wait...");
}

void handlePlayingState() {
  digitalWrite(LED_SPEAKING, HIGH);
  Serial.println("🔊 播放中... 語音輸出");
  updateLCDDisplay("Playing", "Audio output");
}

void handleDisconnectedState() {
  // 閃爍藍牙圖標
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 1000) {
    Serial.println("📱 藍牙未連接，等待配對...");
    updateLCDDisplay("Bluetooth", "Waiting...");
    lastBlink = millis();
  }
}

// === 音頻處理函數 ===

bool checkVoiceActivity() {
  size_t bytesRead;
  esp_err_t result = i2s_read(I2S_NUM_0, audioBuffer, 
                             sizeof(audioBuffer), &bytesRead, 10);
  
  if (result != ESP_OK || bytesRead == 0) {
    return false;
  }
  
  // 計算音頻樣本的RMS值
  long sum = 0;
  int samples = bytesRead / sizeof(int16_t);
  
  for (int i = 0; i < samples; i++) {
    sum += abs(audioBuffer[i]);
  }
  
  int16_t rms = sum / samples;
  
  // 語音活動檢測
  if (rms > SILENCE_THRESHOLD) {
    if (!speechDetected) {
      speechDetected = true;
      Serial.printf("🎤 檢測到語音 (RMS: %d)\n", rms);
    }
    lastSpeechTime = millis();
    
    // 如果正在錄音，將數據添加到緩衝區
    if (recordingActive && bufferIndex < maxBufferSize) {
      size_t samplesToAdd = min((size_t)samples, maxBufferSize - bufferIndex);
      memcpy(&recordingBuffer[bufferIndex], audioBuffer, samplesToAdd * sizeof(int16_t));
      bufferIndex += samplesToAdd;
      
      // 增加調試信息
      if (bufferIndex % 1000 == 0) { // 每1000個樣本顯示一次
        Serial.printf("🎤 錄音進度: %d樣本 (%.1fs)\n", bufferIndex, (float)bufferIndex / SAMPLE_RATE);
      }
    }
    
    return true;
  } else {
    // 即使在靜音時也要收集音頻數據（可能有低音量語音）
    if (recordingActive && bufferIndex < maxBufferSize) {
      size_t samplesToAdd = min((size_t)samples, maxBufferSize - bufferIndex);
      memcpy(&recordingBuffer[bufferIndex], audioBuffer, samplesToAdd * sizeof(int16_t));
      bufferIndex += samplesToAdd;
    }
    
    if (speechDetected && (millis() - lastSpeechTime) > SILENCE_DURATION) {
      speechDetected = false;
      Serial.println("🔇 語音結束");
    }
    return speechDetected;
  }
}

void startRecording() {
  startRecording(false); // 默認為自動語音檢測模式
}

void startRecording(bool manual) {
  if (currentState != IDLE || !bluetoothConnected) {
    return;
  }
  
  manualRecording = manual;
  
  float maxRecordingTime = (float)maxBufferSize / SAMPLE_RATE;
  
  if (manual) {
    float targetDuration = min((float)FIXED_RECORDING_DURATION, maxRecordingTime);
    Serial.printf("🎤 開始手動錄音 (%.1f秒固定時長)...\n", targetDuration);
  } else {
    Serial.printf("🎤 開始自動錄音 (語音檢測, 最大%.1f秒)...\n", maxRecordingTime);
  }
  
  // 重置錄音參數
  bufferIndex = 0;
  recordingStartTime = millis();
  lastSpeechTime = millis();
  recordingActive = true;
  speechDetected = true;
  
  // 更新狀態
  currentState = RECORDING;
  digitalWrite(LED_RECORDING, HIGH);
  
  if (manual) {
    float targetDuration = min((float)FIXED_RECORDING_DURATION, maxRecordingTime);
    Serial.printf("🎤 手動錄音中... 將錄製 %.1f 秒\n", targetDuration);
    updateLCDDisplay("Manual Rec", "Starting...");
  } else {
    Serial.printf("🎤 自動錄音中... 最大 %.1f 秒\n", maxRecordingTime);
    updateLCDDisplay("Auto Rec", "Starting...");
  }
}

void stopRecording() {
  if (currentState != RECORDING) {
    return;
  }
  
  recordingActive = false;
  digitalWrite(LED_RECORDING, LOW);
  
  unsigned long totalDuration = (millis() - recordingStartTime) / 1000;
  
  if (manualRecording) {
    Serial.printf("⏹️ 手動錄音結束，錄製時長: %d秒，共錄製 %d 樣本\n", totalDuration, bufferIndex);
  } else {
    Serial.printf("⏹️ 自動錄音結束，錄製時長: %d秒，共錄製 %d 樣本\n", totalDuration, bufferIndex);
  }
  
  // 重置錄音模式
  manualRecording = false;
  
  // 修復：使用實際錄音時長（毫秒）進行判斷，而不是樣本數
  unsigned long actualDuration = millis() - recordingStartTime;
  
  // 檢查是否有足夠的音頻數據和合理的錄音時長
  bool hasValidAudio = (bufferIndex > 100); // 至少有100個樣本（約6ms的音頻）
  bool hasValidDuration = (actualDuration >= MIN_RECORDING_DURATION); // 至少300ms
  
  Serial.printf("📊 錄音驗證: 樣本數=%d, 實際時長=%dms, 最短時長=%dms\n", 
                bufferIndex, actualDuration, MIN_RECORDING_DURATION);
  
  if (hasValidAudio && (actualDuration >= 100)) { // 降低門檻：至少100ms且有音頻樣本
    // 有效錄音，發送到電腦處理
    Serial.printf("✅ 錄音有效: %d樣本, %dms時長\n", bufferIndex, actualDuration);
    sendAudioToPc();
    currentState = PROCESSING;
    digitalWrite(LED_PROCESSING, HIGH);
    updateLCDDisplay("Processing", "Sending...");
  } else {
    Serial.printf("⚠️ 錄音無效: 樣本=%d (需要>100), 時長=%dms (需要>100ms)\n", 
                  bufferIndex, actualDuration);
    currentState = IDLE;
    updateLCDDisplay("Ready", "Too short");
  }
}

void sendAudioToPc() {
  if (!bluetoothConnected || !pAudioCharacteristic) {
    Serial.println("❌ BLE未連接，無法發送音頻");
    return;
  }
  
  size_t totalBytes = bufferIndex * sizeof(int16_t);
  Serial.printf("📡 準備發送音頻數據: %d 樣本, %d 字節\n", bufferIndex, totalBytes);
  
  // 檢查數據大小是否合理
  if (totalBytes > 500000) { // 大於500KB時發出警告
    Serial.println("⚠️ 音頻數據過大，可能導致傳輸問題");
  }
  
  // 發送音頻頭信息 (格式: 'A' + bufferIndex(4字節) + sampleRate(4字節))
  uint8_t headerData[9]; // 1 + 4 + 4 = 9字節固定格式
  headerData[0] = 'A'; // Audio data identifier
  
  // 強制使用4字節格式發送樣本數和採樣率
  uint32_t samples32 = (uint32_t)bufferIndex;
  uint32_t sampleRate32 = (uint32_t)SAMPLE_RATE;
  
  memcpy(&headerData[1], &samples32, 4);
  memcpy(&headerData[5], &sampleRate32, 4);
  
  // 發送頭部信息
  pAudioCharacteristic->setValue(headerData, sizeof(headerData));
  pAudioCharacteristic->notify();
  Serial.println("📤 音頻頭部信息已發送");
  delay(200); // 增加等待時間確保頭部數據處理完成
  
  // 優化的分塊發送音頻數據
  const size_t chunkSize = 18; // 稍微減小塊大小，留出BLE頭部空間
  size_t totalChunks = (totalBytes + chunkSize - 1) / chunkSize;
  size_t sentChunks = 0;
  
  Serial.printf("📦 開始發送 %d 個數據包...\n", totalChunks);
  
  for (size_t i = 0; i < totalBytes; i += chunkSize) {
    // 檢查連接狀態
    if (!deviceConnected || !bluetoothConnected) {
      Serial.println("❌ BLE連接已斷開，停止發送");
      return;
    }
    
    size_t remainingBytes = min(chunkSize, totalBytes - i);
    uint8_t* dataPtr = (uint8_t*)recordingBuffer + i;
    
    // 設置數據並發送通知
    pAudioCharacteristic->setValue(dataPtr, remainingBytes);
    pAudioCharacteristic->notify();
    
    sentChunks++;
    
    // 每50個包顯示一次進度
    if (sentChunks % 50 == 0) {
      Serial.printf("📊 進度: %d/%d 包 (%.1f%%)\n", 
                   sentChunks, totalChunks, 
                   (float)sentChunks * 100.0 / totalChunks);
    }
    
    // 動態調整延遲時間
    if (sentChunks < 100) {
      delay(30); // 初期較慢
    } else if (sentChunks < 500) {
      delay(25); // 中期適中
    } else {
      delay(20); // 後期較快
    }
  }
  
  Serial.printf("✅ 音頻數據發送完成: %d 包, %d 字節\n", sentChunks, totalBytes);
}

// === 藍牙處理函數 ===

void checkBluetoothConnection() {
  // 檢查BLE連接狀態變化
  if (!deviceConnected && oldDeviceConnected) {
    // 設備斷開連接
    delay(500); // 給BLE堆疊時間準備
    pServer->startAdvertising(); // 重新開始廣播
    Serial.println("📱 重新開始BLE廣播");
    oldDeviceConnected = deviceConnected;
    
    bluetoothConnected = false;
    currentState = BLUETOOTH_DISCONNECTED;
    recordingActive = false;
    digitalWrite(LED_RECORDING, LOW);
    digitalWrite(LED_PROCESSING, LOW);
    digitalWrite(LED_SPEAKING, LOW);
    updateLCDDisplay("Disconnected", "Advertising...");
  }
  
  // 設備連接
  if (deviceConnected && !oldDeviceConnected) {
    oldDeviceConnected = deviceConnected;
    bluetoothConnected = true;
    
    Serial.println("📱 BLE設備已連接");
    Serial.println("📱 系統就緒");
    currentState = IDLE;
    digitalWrite(LED_PROCESSING, LOW);
    digitalWrite(LED_SPEAKING, LOW);
    updateLCDDisplay("Connected", "System Ready");
  }
}

void handleBluetoothData() {
  // BLE通過特徵回調處理，這個函數保留用於兼容性
}

void handleBLECommand(char command) {
  switch (command) {
    case 'P': // Play audio (播放音頻)
      handlePlayAudio();
      break;
      
    case 'S': // Status request (狀態請求)
      sendStatus();
      break;
      
    case 'R': // Ready (處理完成)
      digitalWrite(LED_PROCESSING, LOW);
      currentState = IDLE;
      Serial.println("📱 處理完成，系統就緒");
      break;
      
    case 'E': // Error (錯誤)
      handleError();
      break;
      
    default:
      Serial.printf("⚠️ 未知命令: %c\n", command);
      break;
  }
}

void handlePlayAudio() {
  Serial.println("🔊 接收播放命令，準備播放測試音頻");
  
  currentState = PLAYING;
  digitalWrite(LED_SPEAKING, HIGH);
  updateLCDDisplay("Playing", "Test Audio");
  
  // 播放測試音頻 - 產生一個440Hz的測試音（A音）
  playTestTone(440, 2000); // 440Hz, 2秒
  
  // 播放完成
  digitalWrite(LED_SPEAKING, LOW);
  currentState = IDLE;
  updateLCDDisplay("Ready", getCurrentTime());
  Serial.println("✅ 測試音頻播放完成");
}

void playTestTone(int frequency, int duration_ms) {
  Serial.printf("🎵 播放測試音頻: %dHz, %dms\n", frequency, duration_ms);
  
  // 配置 PWM 輸出 (GPIO26, 使用PWM通道0)
  // 針對不同版本的ESP32 Arduino Core
  #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
    ledcAttach(SPEAKER_PIN, SAMPLE_RATE * 256, 8);  // 新版本: 引腳, 頻率, 解析度
  #else
    ledcSetup(0, SAMPLE_RATE * 256, 8);  // 舊版本: 通道, 頻率, 解析度
    ledcAttachPin(SPEAKER_PIN, 0);
  #endif
  
  // 計算音頻參數
  int samples_per_cycle = SAMPLE_RATE / frequency;
  int total_samples = (SAMPLE_RATE * duration_ms) / 1000;
  
  Serial.printf("📊 音頻參數: 每週期%d樣本, 總共%d樣本\n", samples_per_cycle, total_samples);
  
  // 產生正弦波並輸出
  for (int i = 0; i < total_samples; i++) {
    // 計算正弦波值 (0-255 for PWM)
    float angle = (2.0 * PI * i) / samples_per_cycle;
    int pwm_value = (int)(127.5 + 120 * sin(angle)); // 128 ± 120
    
    // 確保值在有效範圍內
    pwm_value = constrain(pwm_value, 0, 255);
    
    // 輸出到PWM
    #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
      ledcWrite(SPEAKER_PIN, pwm_value);  // 新版本: 直接使用引腳
    #else
      ledcWrite(0, pwm_value);            // 舊版本: 使用通道
    #endif
    
    // 控制採樣率
    delayMicroseconds(1000000 / SAMPLE_RATE);
    
    // 檢查是否需要停止播放
    if (currentState != PLAYING) {
      break;
    }
    
    // 每1000個樣本顯示一次進度
    if (i % 1000 == 0) {
      float progress = (float)i * 100.0 / total_samples;
      Serial.printf("🎵 播放進度: %.1f%%\n", progress);
    }
  }
  
  // 關閉PWM輸出
  #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
    ledcWrite(SPEAKER_PIN, 128); // 新版本: 設為中點，避免爆音
    delay(10);
    ledcDetach(SPEAKER_PIN);
  #else
    ledcWrite(0, 128); // 舊版本: 設為中點，避免爆音
    delay(10);
    ledcDetachPin(SPEAKER_PIN);
  #endif
  Serial.println("🎵 PWM輸出已關閉");
}

void playReceivedAudio(uint8_t* audioData, size_t audioSize) {
  Serial.printf("🎵 播放接收的音頻: %d 字節\n", audioSize);
  
  currentState = PLAYING;
  digitalWrite(LED_SPEAKING, HIGH);
  updateLCDDisplay("Playing", "Received Audio");
  
  // 配置 PWM 輸出 (GPIO26, 使用PWM通道0)
  // 針對不同版本的ESP32 Arduino Core
  #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
    ledcAttach(SPEAKER_PIN, SAMPLE_RATE * 256, 8);  // 新版本: 引腳, 頻率, 解析度
  #else
    ledcSetup(0, SAMPLE_RATE * 256, 8);  // 舊版本: 通道, 頻率, 解析度
    ledcAttachPin(SPEAKER_PIN, 0);
  #endif
  
  // 將16位音頻轉換為PWM輸出
  int16_t* samples = (int16_t*)audioData;
  size_t sampleCount = audioSize / sizeof(int16_t);
  
  Serial.printf("📊 播放參數: %d 樣本\n", sampleCount);
  
  const int playbackDelay = 1000000 / SAMPLE_RATE; // 微秒
  
  for (size_t i = 0; i < sampleCount; i++) {
    // 16位轉8位 (0-255) 使用更好的轉換算法
    int32_t sample = samples[i];
    
    // 增益調整和削波處理
    sample = sample * 2; // 增加音量
    sample = constrain(sample, -32768, 32767);
    
    // 轉換到0-255範圍 (PWM duty cycle)
    uint8_t pwmValue = (sample + 32768) >> 8;
    pwmValue = constrain(pwmValue, 0, 255);
    
    // 輸出到PWM
    #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
      ledcWrite(SPEAKER_PIN, pwmValue);  // 新版本: 直接使用引腳
    #else
      ledcWrite(0, pwmValue);            // 舊版本: 使用通道
    #endif
    
    delayMicroseconds(playbackDelay);
    
    // 檢查是否需要停止播放
    if (currentState != PLAYING) {
      break;
    }
    
    // 每2000個樣本顯示一次進度
    if (i % 2000 == 0) {
      float progress = (float)i * 100.0 / sampleCount;
      Serial.printf("🎵 播放進度: %.1f%%\n", progress);
    }
  }
  
  // 關閉PWM輸出
  #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
    ledcWrite(SPEAKER_PIN, 128); // 新版本: 設為中點，避免爆音
    delay(10);
    ledcDetach(SPEAKER_PIN);
  #else
    ledcWrite(0, 128); // 舊版本: 設為中點，避免爆音
    delay(10);
    ledcDetachPin(SPEAKER_PIN);
  #endif
  digitalWrite(LED_SPEAKING, LOW);
  
  Serial.println("✅ 音頻播放完成");
  currentState = IDLE;
  updateLCDDisplay("Ready", getCurrentTime());
}



void sendStatus() {
  if (!bluetoothConnected || !pCommandCharacteristic) {
    return;
  }
  
  uint8_t statusData[4];
  statusData[0] = 'S'; // Status response
  statusData[1] = (uint8_t)currentState;
  statusData[2] = bluetoothConnected ? 1 : 0;
  statusData[3] = recordingActive ? 1 : 0;
  
  pCommandCharacteristic->setValue(statusData, 4);
  pCommandCharacteristic->notify();
}

void handleError() {
  Serial.println("❌ 收到錯誤信號");
  digitalWrite(LED_PROCESSING, LOW);
  currentState = IDLE;
  Serial.println("📱 處理錯誤，請重試");
}

// === 按鈕處理函數 ===

void checkButtons() {
  static unsigned long lastButtonCheck = 0;
  static bool lastRecordState = HIGH;
  static bool lastModeState = HIGH;
  
  if (millis() - lastButtonCheck < 50) { // 防抖動
    return;
  }
  
  bool recordButton = digitalRead(RECORD_BUTTON);
  bool modeButton = digitalRead(MODE_BUTTON);
  
  // 錄音按鈕 (下降沿觸發)
  if (lastRecordState == HIGH && recordButton == LOW) {
    if (currentState == IDLE) {
      startRecording(true); // 按鈕觸發為手動錄音模式（15秒固定）
    } else if (currentState == RECORDING) {
      Serial.println("🔘 按鈕強制停止錄音");
      stopRecording();
    }
  }
  
  // 模式按鈕 (下降沿觸發)
  if (lastModeState == HIGH && modeButton == LOW) {
    handleModeButton();
  }
  
  lastRecordState = recordButton;
  lastModeState = modeButton;
  lastButtonCheck = millis();
}

void handleModeButton() {
  Serial.println("🔘 模式按鈕按下");
  
  // 根據當前狀態執行不同操作
  switch (currentState) {
    case IDLE:
      // 顯示系統信息
      showSystemInfo();
      break;
      
    case RECORDING:
      // 強制停止錄音
      stopRecording();
      break;
      
    case PROCESSING:
      // 取消處理
      currentState = IDLE;
      digitalWrite(LED_PROCESSING, LOW);
      Serial.println("📱 操作取消，系統就緒");
      break;
      
    case PLAYING:
      // 停止播放
      currentState = IDLE;
      digitalWrite(LED_SPEAKING, LOW);
      Serial.println("📱 播放停止，系統就緒");
      break;
      
    default:
      break;
  }
}

void showSystemInfo() {
  Serial.println("📊 顯示系統信息");
  
  // 循環顯示不同信息
  static int infoIndex = 0;
  
  switch (infoIndex) {
    case 0:
      Serial.println("📱 ESP32-VoiceMic v1.1");
      break;
    case 1:
      Serial.println("📱 Bluetooth: " + String(bluetoothConnected ? "Connected" : "Disconnected"));
      break;
    case 2:
      Serial.println("📱 Memory: " + String(ESP.getFreeHeap()) + " bytes");
      break;
    case 3:
      Serial.println("📱 Uptime: " + String(millis()/1000) + " sec");
      break;
  }
  
  infoIndex = (infoIndex + 1) % 4;
}

// === 輔助函數 ===

void printMemoryInfo(String stage) {
  Serial.printf("📊 %s - 可用內存: %d 字節\n", stage.c_str(), ESP.getFreeHeap());
}

String getCurrentTime() {
  unsigned long uptime = millis() / 1000;
  int hours = uptime / 3600;
  int minutes = (uptime % 3600) / 60;
  int seconds = uptime % 60;
  
  return String(hours) + ":" + 
         (minutes < 10 ? "0" : "") + String(minutes) + ":" +
         (seconds < 10 ? "0" : "") + String(seconds);
}

// === 錯誤處理 ===

void handleSystemError(String error) {
  Serial.println("❌ 系統錯誤: " + error);
  
  // 重置系統狀態
  currentState = IDLE;
  recordingActive = false;
  
  // 關閉所有LED
  digitalWrite(LED_RECORDING, LOW);
  digitalWrite(LED_PROCESSING, LOW);
  digitalWrite(LED_SPEAKING, LOW);
  
  // 顯示錯誤信息
  updateLCDDisplay("Error", error.substring(0, 14));
}

// === LCD顯示函數 ===

void updateLCDDisplay(String line1, String line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1.substring(0, LCD_COLS)); // 限制長度
  
  if (line2.length() > 0) {
    lcd.setCursor(0, 1);
    lcd.print(line2.substring(0, LCD_COLS)); // 限制長度
  }
}
