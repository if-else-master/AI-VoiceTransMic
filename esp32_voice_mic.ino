/*
 * ESP32 AI語音翻譯麥克風系統
 * 
 * 硬件配置:
 * - ESP32-WROOM-32
 * - INMP441 MEMS 麥克風
 * - I2C LCD 1602 顯示器
 * - 喇叭 (8Ω 0.5W)
 * 
 * 功能:
 * - 即時音頻捕獲
 * - 藍牙音頻傳輸
 * - LCD 狀態顯示
 * - 語音播放
 * 
 * 作者: Your Name
 * 版本: 1.0
 * 日期: 2024
 */

#include "BluetoothSerial.h"
#include <WiFi.h>
#include <LiquidCrystal_I2C.h>
#include <driver/i2s.h>
#include <driver/dac.h>

// === 硬件配置 ===
// INMP441 麥克風引腳配置
#define I2S_WS 25     // LRCK (Left/Right Clock)
#define I2S_SD 33     // DOUT (Serial Data Out)  
#define I2S_SCK 32    // BCLK (Bit Clock)

// 喇叭 DAC 輸出
#define SPEAKER_PIN 26  // DAC 輸出引腳

// I2C LCD 配置
#define LCD_ADDR 0x27   // I2C 地址
#define LCD_COLS 16     // 列數
#define LCD_ROWS 2      // 行數

// 控制按鈕
#define RECORD_BUTTON 2   // 錄音按鈕
#define MODE_BUTTON 4     // 模式切換按鈕

// LED 指示燈
#define LED_RECORDING 5   // 錄音指示燈
#define LED_PROCESSING 18 // 處理指示燈
#define LED_SPEAKING 19   // 播放指示燈

// === 音頻參數 ===
#define SAMPLE_RATE 16000      // 採樣率 16kHz
#define BITS_PER_SAMPLE 16     // 16位音頻
#define CHANNELS 1             // 單聲道
#define BUFFER_SIZE 1024       // 緩衝區大小
#define MAX_AUDIO_DURATION 10  // 最大錄音時長（秒）

// === 全局變量 ===
BluetoothSerial SerialBT;
LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);

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

// 語音活動檢測
const int16_t SILENCE_THRESHOLD = 500;
const unsigned long SILENCE_DURATION = 1000;  // 1秒靜音
const unsigned long MIN_RECORDING_DURATION = 300; // 最短錄音300ms
unsigned long lastSpeechTime = 0;
bool speechDetected = false;

// 自定義字符 (LCD顯示圖標)
byte micIcon[8] = {
  0b00100,
  0b01110,
  0b01110,
  0b01110,
  0b01110,
  0b11111,
  0b00100,
  0b00000
};

byte speakerIcon[8] = {
  0b00001,
  0b00011,
  0b01111,
  0b01111,
  0b01111,
  0b00011,
  0b00001,
  0b00000
};

byte bluetoothIcon[8] = {
  0b00100,
  0b10110,
  0b01101,
  0b00110,
  0b00110,
  0b01101,
  0b10110,
  0b00100
};

void setup() {
  Serial.begin(115200);
  Serial.println("🎤 ESP32 AI語音翻譯麥克風系統啟動中...");
  
  // 初始化硬件
  initGPIO();
  initLCD();
  initI2S();
  initBluetooth();
  initAudioBuffer();
  
  Serial.println("✅ 系統初始化完成！");
  updateLCD("系統就緒", "等待連接...");
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

void initLCD() {
  lcd.init();
  lcd.backlight();
  
  // 創建自定義字符
  lcd.createChar(0, micIcon);
  lcd.createChar(1, speakerIcon);
  lcd.createChar(2, bluetoothIcon);
  
  // 顯示啟動信息
  lcd.setCursor(0, 0);
  lcd.print("AI Voice Mic");
  lcd.setCursor(0, 1);
  lcd.print("Initializing...");
  
  Serial.println("✅ LCD 初始化完成");
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

void initBluetooth() {
  if (!SerialBT.begin("ESP32-VoiceMic")) {
    Serial.println("❌ 藍牙初始化失敗");
    return;
  }
  
  Serial.println("✅ 藍牙初始化完成");
  Serial.println("📱 設備名稱: ESP32-VoiceMic");
  Serial.println("📡 等待藍牙連接...");
}

void initAudioBuffer() {
  maxBufferSize = SAMPLE_RATE * MAX_AUDIO_DURATION;
  recordingBuffer = (int16_t*)malloc(maxBufferSize * sizeof(int16_t));
  
  if (recordingBuffer == NULL) {
    Serial.println("❌ 音頻緩衝區分配失敗");
    return;
  }
  
  Serial.printf("✅ 音頻緩衝區分配成功: %d 樣本\n", maxBufferSize);
}

// === 狀態處理函數 ===

void handleIdleState() {
  // 自動語音檢測
  if (checkVoiceActivity()) {
    startRecording();
  }
  
  // 更新空閒顯示
  static unsigned long lastUpdate = 0;
  if (millis() - lastUpdate > 2000) {
    updateLCD("就緒", getCurrentTime());
    lastUpdate = millis();
  }
}

void handleRecordingState() {
  // 檢查錄音時長限制
  if (millis() - recordingStartTime > MAX_AUDIO_DURATION * 1000) {
    Serial.println("⏰ 達到最大錄音時長，停止錄音");
    stopRecording();
    return;
  }
  
  // 檢查語音活動
  if (!checkVoiceActivity()) {
    // 檢查靜音時長
    if (millis() - lastSpeechTime > SILENCE_DURATION) {
      if (millis() - recordingStartTime > MIN_RECORDING_DURATION) {
        Serial.println("🔇 檢測到靜音，停止錄音");
        stopRecording();
      }
    }
  }
  
  // 更新錄音顯示
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 500) {
    digitalWrite(LED_RECORDING, !digitalRead(LED_RECORDING));
    
    int duration = (millis() - recordingStartTime) / 1000;
    updateLCD("🎤 錄音中...", String("時長: ") + String(duration) + "s");
    lastBlink = millis();
  }
}

void handleProcessingState() {
  // 閃爍處理LED
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 300) {
    digitalWrite(LED_PROCESSING, !digitalRead(LED_PROCESSING));
    lastBlink = millis();
  }
  
  updateLCD("🔄 處理中...", "請稍候");
}

void handlePlayingState() {
  digitalWrite(LED_SPEAKING, HIGH);
  updateLCD("🔊 播放中...", "語音輸出");
}

void handleDisconnectedState() {
  // 閃爍藍牙圖標
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 1000) {
    updateLCD("藍牙未連接", "等待配對...");
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
      memcpy(&recordingBuffer[bufferIndex], audioBuffer, 
             min(bytesRead, (maxBufferSize - bufferIndex) * sizeof(int16_t)));
      bufferIndex += samples;
    }
    
    return true;
  } else {
    if (speechDetected && (millis() - lastSpeechTime) > SILENCE_DURATION) {
      speechDetected = false;
      Serial.println("🔇 語音結束");
    }
    return speechDetected;
  }
}

void startRecording() {
  if (currentState != IDLE || !bluetoothConnected) {
    return;
  }
  
  Serial.println("🎤 開始錄音...");
  
  // 重置錄音參數
  bufferIndex = 0;
  recordingStartTime = millis();
  lastSpeechTime = millis();
  recordingActive = true;
  speechDetected = true;
  
  // 更新狀態
  currentState = RECORDING;
  digitalWrite(LED_RECORDING, HIGH);
  
  updateLCD("🎤 錄音中...", "開始錄音");
}

void stopRecording() {
  if (currentState != RECORDING) {
    return;
  }
  
  recordingActive = false;
  digitalWrite(LED_RECORDING, LOW);
  
  Serial.printf("⏹️ 錄音結束，共錄製 %d 樣本\n", bufferIndex);
  
  if (bufferIndex > SAMPLE_RATE * MIN_RECORDING_DURATION / 1000) {
    // 有效錄音，發送到電腦處理
    sendAudioToPc();
    currentState = PROCESSING;
    digitalWrite(LED_PROCESSING, HIGH);
  } else {
    Serial.println("⚠️ 錄音時間過短，忽略");
    currentState = IDLE;
  }
}

void sendAudioToPc() {
  if (!bluetoothConnected) {
    Serial.println("❌ 藍牙未連接，無法發送音頻");
    return;
  }
  
  Serial.printf("📡 發送音頻數據: %d 字節\n", bufferIndex * 2);
  
  // 發送音頻頭信息
  SerialBT.write('A'); // Audio data identifier
  SerialBT.write((uint8_t*)&bufferIndex, sizeof(size_t));
  SerialBT.write((uint8_t*)&SAMPLE_RATE, sizeof(int));
  
  // 分塊發送音頻數據
  const size_t chunkSize = 512;
  for (size_t i = 0; i < bufferIndex; i += chunkSize) {
    size_t remainingBytes = min(chunkSize, bufferIndex - i) * sizeof(int16_t);
    SerialBT.write((uint8_t*)&recordingBuffer[i], remainingBytes);
    delay(10); // 小延遲確保數據傳輸穩定
  }
  
  Serial.println("✅ 音頻數據發送完成");
}

// === 藍牙處理函數 ===

void checkBluetoothConnection() {
  bool connected = SerialBT.hasClient();
  
  if (connected != bluetoothConnected) {
    bluetoothConnected = connected;
    
    if (connected) {
      Serial.println("📱 藍牙設備已連接");
      updateLCD("藍牙已連接", "系統就緒");
      currentState = IDLE;
      digitalWrite(LED_PROCESSING, LOW);
      digitalWrite(LED_SPEAKING, LOW);
    } else {
      Serial.println("📱 藍牙設備已斷開");
      currentState = BLUETOOTH_DISCONNECTED;
      recordingActive = false;
      digitalWrite(LED_RECORDING, LOW);
      digitalWrite(LED_PROCESSING, LOW);
      digitalWrite(LED_SPEAKING, LOW);
    }
  }
}

void handleBluetoothData() {
  if (!SerialBT.available()) {
    return;
  }
  
  char command = SerialBT.read();
  
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
      updateLCD("處理完成", "系統就緒");
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
  Serial.println("🔊 接收播放命令");
  
  // 讀取音頻數據大小
  size_t audioSize;
  if (SerialBT.readBytes((uint8_t*)&audioSize, sizeof(size_t)) != sizeof(size_t)) {
    Serial.println("❌ 無法讀取音頻大小");
    return;
  }
  
  Serial.printf("📥 接收音頻數據: %d 字節\n", audioSize);
  
  // 分配臨時緩衝區
  uint8_t* audioData = (uint8_t*)malloc(audioSize);
  if (audioData == NULL) {
    Serial.println("❌ 音頻緩衝區分配失敗");
    return;
  }
  
  // 接收音頻數據
  size_t totalReceived = 0;
  while (totalReceived < audioSize) {
    size_t bytesToRead = min(audioSize - totalReceived, (size_t)512);
    size_t bytesRead = SerialBT.readBytes(&audioData[totalReceived], bytesToRead);
    totalReceived += bytesRead;
    
    if (bytesRead == 0) {
      delay(10); // 等待更多數據
    }
  }
  
  if (totalReceived == audioSize) {
    Serial.println("✅ 音頻數據接收完成");
    playAudio(audioData, audioSize);
  } else {
    Serial.printf("❌ 音頻數據接收不完整: %d/%d\n", totalReceived, audioSize);
  }
  
  free(audioData);
}

void playAudio(uint8_t* audioData, size_t audioSize) {
  currentState = PLAYING;
  digitalWrite(LED_SPEAKING, HIGH);
  
  // 配置 DAC 輸出
  dac_output_enable(DAC_CHANNEL_1);
  
  // 將16位音頻轉換為8位DAC輸出
  int16_t* samples = (int16_t*)audioData;
  size_t sampleCount = audioSize / sizeof(int16_t);
  
  const int playbackDelay = 1000000 / SAMPLE_RATE; // 微秒
  
  for (size_t i = 0; i < sampleCount; i++) {
    // 16位轉8位 (0-255)
    uint8_t dacValue = (samples[i] + 32768) >> 8;
    dac_output_voltage(DAC_CHANNEL_1, dacValue);
    
    delayMicroseconds(playbackDelay);
    
    // 檢查是否需要停止播放
    if (currentState != PLAYING) {
      break;
    }
  }
  
  dac_output_disable(DAC_CHANNEL_1);
  digitalWrite(LED_SPEAKING, LOW);
  
  Serial.println("✅ 音頻播放完成");
  currentState = IDLE;
  updateLCD("播放完成", "系統就緒");
}

void sendStatus() {
  SerialBT.write('S'); // Status response
  SerialBT.write((uint8_t)currentState);
  SerialBT.write(bluetoothConnected ? 1 : 0);
  SerialBT.write(recordingActive ? 1 : 0);
}

void handleError() {
  Serial.println("❌ 收到錯誤信號");
  digitalWrite(LED_PROCESSING, LOW);
  currentState = IDLE;
  updateLCD("處理錯誤", "請重試");
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
      startRecording();
    } else if (currentState == RECORDING) {
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
      updateLCD("操作取消", "系統就緒");
      break;
      
    case PLAYING:
      // 停止播放
      currentState = IDLE;
      digitalWrite(LED_SPEAKING, LOW);
      updateLCD("播放停止", "系統就緒");
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
      updateLCD("ESP32-VoiceMic", "v1.0");
      break;
    case 1:
      updateLCD("Bluetooth:", bluetoothConnected ? "Connected" : "Disconnected");
      break;
    case 2:
      updateLCD("Memory:", String(ESP.getFreeHeap()) + " bytes");
      break;
    case 3:
      updateLCD("Uptime:", String(millis()/1000) + " sec");
      break;
  }
  
  infoIndex = (infoIndex + 1) % 4;
}

// === 輔助函數 ===

void updateLCD(String line1, String line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
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
  updateLCD("系統錯誤", error);
  
  // 重置系統狀態
  currentState = IDLE;
  recordingActive = false;
  
  // 關閉所有LED
  digitalWrite(LED_RECORDING, LOW);
  digitalWrite(LED_PROCESSING, LOW);
  digitalWrite(LED_SPEAKING, LOW);
}
