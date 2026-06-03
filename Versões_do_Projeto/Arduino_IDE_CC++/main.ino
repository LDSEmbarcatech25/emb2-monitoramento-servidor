#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "PubSubClient.h"
#include "LittleFS.h"
#include "esp_camera.h"

// =============================================================================
// DEFINIÇÃO DE PINOS DA PLACA KiiRA v2.0 (MAPEAMENTO C++ ESP32-S3)
// =============================================================================
#define PIN_RELE   48
#define PIN_BOTAO  46
#define PIN_SDA    14
#define PIN_SCL    21

// Pinos exatos do barramento óptico da KiiRA v2.0
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM      4
#define SIOC_GPIO_NUM      5
#define Y9_GPIO_NUM       16
#define Y8_GPIO_NUM       17
#define Y7_GPIO_NUM       18
#define Y6_GPIO_NUM       12
#define Y5_GPIO_NUM       10
#define Y4_GPIO_NUM        8
#define Y3_GPIO_NUM        9
#define Y2_GPIO_NUM       11
#define VSYNC_GPIO_NUM     6
#define HREF_GPIO_NUM      7
#define PCLK_GPIO_NUM     13

// =============================================================================
// CONFIGURAÇÕES IoT E LIMITES
// =============================================================================
const char* WIFI_SSID = "ITSelf";
const char* WIFI_PASS = "code2020";

const char* MQTT_BROKER = "io.adafruit.com";
const int   MQTT_PORT   = 1883;
const char* MQTT_USER   = "rafaelbrandaorb";
const char* MQTT_KEY    = "aio_pkac63za0hDRftR2ayLgkrsvb7sl";

const int LIMITE_FOTOS = 10; // Limite rotativo do LittleFS igual ao Python

// Variáveis Globais de Controle e Telemetria
float temp_local = 0.0;
float umid_local = 0.0;
String status_local = "ONLINE";
bool disparar_reset = false;
unsigned long ultimo_clique = 0;
bool camera_inicializada = false;

// Sistema Rotativo de Logs (Live Log Terminal)
const int TOTAL_LOGS = 5;
String logs_sistema[TOTAL_LOGS] = {"", "", "", "", ""};

// Periféricos
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
WiFiClient espClient;
PubSubClient mqttClient(espClient);
WebServer server(8080);

// =============================================================================
// SISTEMA DE LOGS EM TEMPO REAL
// =============================================================================
void adicionarLog(String texto) {
    unsigned long segundos = millis() / 1000;
    String novaMensagem = "[" + String(segundos) + "s] " + texto;
    Serial.println(novaMensagem);
    
    for (int i = 0; i < TOTAL_LOGS - 1; i++) {
        logs_sistema[i] = logs_sistema[i + 1];
    }
    logs_sistema[TOTAL_LOGS - 1] = novaMensagem;
}

void IRAM_ATTR tratarBotaoLocal() {
    unsigned long agora = millis();
    if (agora - ultimo_clique > 300) {
        ultimo_clique = agora;
        disparar_reset = true;
    }
}

// =============================================================================
// INICIALIZAÇÃO CORRIGIDA DO HARDWARE DA CÂMERA
// =============================================================================
bool inicializarCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    
    // Configurações cruciais de timing estável para o chip ESP32-S3 da KiiRA
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 10; 
    config.fb_count = 2; // Alocação de buffer duplo para evitar perda de frame (Impedir tela preta)
    config.fb_location = CAMERA_FB_IN_PSRAM;

    esp_err_t err = esp_camera_init(&config);
    if (err == ESP_OK) {
        sensor_t * s = esp_camera_sensor_get();
        if (s) {
            s->set_vflip(s, 1);   // Ajusta orientação vertical se necessário
            s->set_hmirror(s, 0); // Ajusta espelhamento
        }
        return true;
    }
    return false;
}

void lerSensorHDC() {
    Wire.beginTransmission(0x40);
    Wire.write(0x00);
    Wire.endTransmission();
    delay(40);
    
    if (Wire.requestFrom(0x40, 4) == 4) {
        uint16_t temp_raw = (Wire.read() << 8) | Wire.read();
        uint16_t umid_raw = (Wire.read() << 8) | Wire.read();
        temp_local = (temp_raw / 65536.0) * 165.0 - 40.0;
        umid_local = (umid_raw / 65536.0) * 100.0;
    }
}

void atualizarOled(String l1, String l2, String l3) {
    oled.clearDisplay();
    oled.setTextSize(1);
    oled.setTextColor(SSD1306_WHITE);
    oled.setCursor(5, 0);
    oled.println("Gestor_Kiira");
    oled.println("----------------");
    oled.setCursor(0, 25);  oled.println(l1);
    oled.setCursor(0, 40);  oled.println(l2);
    oled.setCursor(0, 55);  oled.println(l3);
    oled.display();
}

// =============================================================================
// LAYOUT PROFISSIONAL IGUAL À IMAGEM DO PYTHON + AJAX INTEGRADO
// =============================================================================
void handleRoot() {
    String html = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n";
    html += "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='UTF-8'>";
    html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
    html += "<title>Gestor Kiira - Painel Operacional</title>";
    html += "<style>";
    html += "body { font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }";
    html += "h2 { color: #38bdf8; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 1px; }";
    html += ".sub { color: #94a3b8; font-size: 14px; margin-bottom: 25px; }";
    html += ".container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; max-width: 1000px; width:100%; }";
    html += ".card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; width: 280px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); display: flex; flex-direction: column; align-items: center; justify-content: center; }";
    html += ".card-video { width: 100%; max-width: 440px; }";
    html += ".card-galeria { width: 100%; max-width: 440px; }";
    html += ".card-serial { width: 100%; max-width: 940px; background: #020617; border-color: #1e293b; align-items: flex-start; justify-content: flex-start; }";
    html += ".val { font-size: 36px; font-weight: bold; color: #f1f5f9; margin-top: 10px; }";
    html += ".unit { font-size: 18px; color: #38bdf8; }";
    html += ".status { padding: 6px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; text-transform: uppercase; margin-top: 10px; margin-bottom: 15px; }";
    html += ".online { background: #065f46; color: #34d399; } .resetting { background: #991b1b; color: #fca5a5; }";
    html += ".btn { background: #e11d48; color: white; border: none; padding: 14px 28px; font-size: 14px; font-weight: bold; border-radius: 8px; cursor: pointer; transition: 0.2s; text-decoration: none; text-align: center; width: 80%; display: block; margin-top: 5px; }";
    html += "pre { margin: 10px 0 0 0; color: #4ade80; font-family: monospace; font-size: 12px; line-height: 1.5; background: #020617; width: 100%; overflow-x: auto; white-space: pre-wrap; }";
    html += "img { width: 100%; max-height: 260px; object-fit: contain; border-radius: 8px; border: 1px solid #334155; background: #020617; }";
    html += ".lista-arquivos { width: 100%; margin-top: 10px; max-height: 210px; overflow-y: auto; }";
    html += ".item-arquivo { display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 8px 12px; margin-bottom: 6px; border-radius: 6px; font-size: 14px; }";
    html += ".btn-view { background: #38bdf8; color: #0f172a; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; }";
    html += ".btn-del { background: #ef4444; color: white; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; margin-left: 5px; }";
    html += "</style>";
    
    html += "<script>";
    html += "setInterval(function() {";
    html += "  fetch('/api/data').then(res => res.json()).then(data => {";
    html += "    document.getElementById('temp').innerHTML = data.temperatura + '<span class=\"unit\">°C</span>';";
    html += "    document.getElementById('umid').innerHTML = data.umidade + '<span class=\"unit\">%</span>';";
    html += "    let stEl = document.getElementById('status_box');";
    html += "    stEl.innerText = data.status; stEl.className = 'status ' + (data.status === 'ONLINE' ? 'online' : 'resetting');";
    html += "    let logHtml = ''; data.logs.forEach(l => { if(l !== '') logHtml += l + '\\n'; });";
    html += "    document.getElementById('serial_term').innerText = logHtml;";
    html += "  });";
    html += "}, 2000);";
    html += "function capturarFoto() {";
    html += "  let b = document.getElementById('btn_cap'); b.innerText = 'Capturando...'; b.style.background = '#047857';";
    html += "  fetch('/capturar_agora').then(r => r.text()).then(msg => { alert(msg); window.location.reload(); });";
    html += "}";
    html += "</script>";
    html += "</head><body>";
    
    html += "<h2>Gestor KiiRA 2.0</h2>";
    html += "<div class='sub'>Centro de Controle Operacional de TI (Armazenamento LittleFS)</div>";
    html += "<div class='container'>";
    
    // Card Vídeo Transmissão
    html += "<div class='card card-video'>";
    html += "<h3 style='margin:0 0 10px 0; color:#94a3b8;'>Monitoramento de Vídeo Local</h3>";
    if (camera_inicializada) {
        html += "<img src='/video'><p style='color:#34d399; font-size:12px; margin:5px 0 0 0;'>Transmissão QVGA Ativa (OV5640)</p>";
    } else {
        html += "<div style='width:100%; height:200px; background:#000; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#ef4444;'>Câmera Offline (Verifique o Flat)</div>";
    }
    html += "<button id='btn_cap' onclick='capturarFoto()' class='btn' style='background:#10b981; margin-top:15px;'>📸 DISPARAR E SALVAR FOTO</button>";
    html += "</div>";
    
    // Bloco central de métricas
    html += "<div style='display:flex; flex-direction:column; gap:20px;'>";
    html += "  <div class='card'><span style='color:#94a3b8; font-weight:500;'>Temperatura do Rack</span><div id='temp' class='val'>" + String(temp_local, 1) + "<span class='unit'>°C</span></div></div>";
    html += "  <div class='card'><span style='color:#94a3b8; font-weight:500;'>Umidade do Ambiente</span><div id='umid' class='val'>" + String(umid_local, 1) + "<span class='unit'>%</span></div></div>";
    html += "  <div class='card'><span style='color:#94a3b8; font-weight:500;'>Status da Placa</span><div id='status_box' class='status " + String(status_local == "ONLINE" ? "online" : "resetting") + "'>" + status_local + "</div><a href='/action_reset' class='btn'>FORÇAR HARD RESET</a></div>";
    html += "</div>";
    
    // Card Galeria Flash (LittleFS)
    html += "<div class='card card-galeria'>";
    html += "<h3 style='margin:0 0 10px 0; color:#38bdf8;'>Galeria Interna (Flash)</h3>";
    html += "<div class='lista-arquivos'>";
    
    File root = LittleFS.open("/fotos");
    int contador = 0;
    if (root && root.isDirectory()) {
        File file = root.openNextFile();
        while (file) {
            String fName = file.name();
            if (fName.endsWith(".jpg")) {
                contador++;
                html += "<div class='item-arquivo'><span>📂 " + fName + "</span><div>";
                html += "<a href='/ver?file=" + fName + "' target='_blank' class='btn-view'>👁️ VER</a>";
                html += "<a href='/deletar?file=" + fName + "' class='btn-del'>🗑️</a></div></div>";
            }
            file = root.openNextFile();
        }
    }
    if (contador == 0) {
        html += "<div style='color:#64748b; font-style:italic; text-align:center; padding-top:20px;'>Nenhuma foto salva na Flash.</div>";
    }
    html += "</div>";
    html += "<a href='/' class='btn' style='background:#475569; margin-top:15px;'>🔄 ATUALIZAR LISTA</a>";
    html += "</div>";
    
    // Card Terminal Live Log
    html += "<div class='card card-serial'>";
    html += "<span style='color:#38bdf8; font-weight:bold; font-size: 14px; text-transform: uppercase;'>Monitor Serial Web (Live Log)</span>";
    html += "<pre id='serial_term'>";
    for (int i = 0; i < TOTAL_LOGS; i++) {
        if (logs_sistema[i] != "") html += logs_sistema[i] + "\n";
    }
    html += "</pre></div>";
    
    html += "</div></body></html>";
    server.send(200, "text/html", html);
}

// =============================================================================
// STREAM DE VÍDEO (CORRIGIDO PARA REQUISIÇÃO ASSÍNCRONA)
// =============================================================================
void handleVideo() {
    WiFiClient client = server.client();
    String response = "HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
    client.print(response);

    for (int i = 0; i < 15; i++) {
        camera_fb_t * fb = esp_camera_fb_get();
        if (!fb) break;

        client.print("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + String(fb->len) + "\r\n\r\n");
        client.write(fb->buf, fb->len);
        client.print("\r\n");
        
        esp_camera_fb_return(fb);
        delay(100);
    }
}

// =============================================================================
// CAPTURA ROTATIVA DE ATÉ 10 IMAGENS (SISTEMA IGUAL AO SEU EM PYTHON)
// =============================================================================
void handleCapturarAgora() {
    if (!camera_inicializada) {
        server.send(500, "text/plain", "Hardware da camera indisponivel.");
        return;
    }

    // Contagem e gerenciamento rotativo de fotos
    int total_fotos = 0;
    String foto_mais_antiga = "";
    unsigned long menor_timestamp = 4294967295;

    File root = LittleFS.open("/fotos");
    if (root && root.isDirectory()) {
        File file = root.openNextFile();
        while (file) {
            String fName = file.name();
            if (fName.endsWith(".jpg")) {
                total_fotos++;
                // Extrai timestamp do nome para achar a mais antiga
                String ts_str = fName.substring(5, fName.indexOf(".jpg"));
                unsigned long ts = ts_str.toInt();
                if (ts < menor_timestamp) {
                    menor_timestamp = ts;
                    foto_mais_antiga = fName;
                }
            }
            file = root.openNextFile();
        }
    }

    // Se bater o limite de 10 fotos definido pelo projeto, deleta a mais antiga
    if (total_fotos >= LIMITE_FOTOS && foto_mais_antiga != "") {
        LittleFS.remove("/fotos/" + foto_mais_antiga);
        adicionarLog("Limite atingido. Foto antiga removida: " + foto_mais_antiga);
    }

    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        server.send(200, "text/plain", "Falha ao capturar frame do hardware.");
        return;
    }

    String path = "/fotos/foto_" + String(millis()) + ".jpg";
    File file = LittleFS.open(path, FILE_WRITE);
    if (!file) {
        esp_camera_fb_return(fb);
        server.send(200, "text/plain", "Erro de gravacao no LittleFS.");
        return;
    }

    file.write(fb->buf, fb->len);
    file.close();
    esp_camera_fb_return(fb);

    adicionarLog("Foto registrada no LittleFS: " + path.substring(7));
    server.send(200, "text/plain", "Sucesso! Foto armazenada na Flash.");
}

// Visualizador individual das fotos
void handleVerFoto() {
    if (server.hasArg("file")) {
        String path = "/fotos/" + server.arg("file");
        if (LittleFS.exists(path)) {
            File file = LittleFS.open(path, FILE_READ);
            server.streamFile(file, "image/jpeg");
            file.close();
            return;
        }
    }
    server.send(404, "text/plain", "Arquivo ausente.");
}

void handleDeletarFoto() {
    if (server.hasArg("file")) {
        String path = "/fotos/" + server.arg("file");
        if (LittleFS.exists(path)) {
            LittleFS.remove(path);
            adicionarLog("Arquivo removido da Flash: " + server.arg("file"));
        }
    }
    server.sendHeader("Location", "/");
    server.send(303, "text/plain", "");
}

void handleApiData() {
    String json = "{";
    json += "\"temperatura\":" + String(temp_local, 1) + ",";
    json += "\"umidade\":" + String(umid_local, 1) + ",";
    json += "\"status\":\"" + status_local + "\",";
    json += "\"logs\":[";
    for (int i = 0; i < TOTAL_LOGS; i++) {
        json += "\"" + logs_sistema[i] + "\"";
        if (i < TOTAL_LOGS - 1) json += ",";
    }
    json += "]}";
    server.send(200, "application/json", json);
}

void handleReset() {
    disparar_reset = true;
    server.sendHeader("Location", "/");
    server.send(303, "text/plain", "");
}

// =============================================================================
// CALLBACKS E RECONEXÃO MQTT
// =============================================================================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String msg = "";
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
    if (msg == "1" || msg == "HARD_RESET") {
        adicionarLog("Nuvem Adafruit enviou comando: HARD_RESET");
        disparar_reset = true;
    }
}

void reconectarMQTT() {
    if (!mqttClient.connected()) {
        String clientId = "kiira_" + String(random(10, 99));
        if (mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_KEY)) {
            adicionarLog("Sincronizado com Adafruit Cloud.");
            String topicoComandos = String(MQTT_USER) + "/feeds/comandos";
            mqttClient.subscribe(topicoComandos.c_str());
        }
    }
}

// =============================================================================
// SETUP E LOOP PRINCIPAL
// =============================================================================
void setup() {
    Serial.begin(115200);
    
    pinMode(PIN_RELE, OUTPUT);
    digitalWrite(PIN_RELE, HIGH);
    
    pinMode(PIN_BOTAO, INPUT_PULLUP);
    attachInterrupt(PIN_BOTAO, tratarBotaoLocal, FALLING);

    Wire.begin(PIN_SDA, PIN_SCL, 100000);
    if(oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        oled.clearDisplay();
        oled.display();
    }

    adicionarLog("Checando integridade do sistema de arquivos interno...");
    if (!LittleFS.begin(true)) {
        adicionarLog("Falha critica ao gerenciar LittleFS.");
    } else {
        if (!LittleFS.exists("/fotos")) {
            LittleFS.mkdir("/fotos");
            adicionarLog("Pasta /fotos criada com sucesso no LittleFS interno.");
        }
    }

    // Inicialização do hardware óptico
    if (!inicializarCamera()) {
        adicionarLog("Falha critica na inicializacao da camera!");
        camera_inicializada = false;
    } else {
        adicionarLog("Modulo optico OV5640 ativo via Hardware (QVGA).");
        camera_inicializada = true;
    }

    WiFi.begin(WIFI_SSID, WIFI_PASS);
    atualizarOled("Conectando Wi-Fi", WIFI_SSID, "Aguarde...");
    
    int timeout = 0;
    while (WiFi.status() != WL_CONNECTED && timeout < 15) {
        delay(500);
        timeout++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        adicionarLog("Conectado com IP: " + WiFi.localIP().toString());
        atualizarOled("Wi-Fi Conectado!", WiFi.localIP().toString(), "Conectando MQTT...");
        mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
        mqttClient.setCallback(mqttCallback);
        reconectarMQTT();
    } else {
        WiFi.disconnect();
        WiFi.softAP("Gestor_Kiira", "kiira2026");
        adicionarLog("Roteadores ausentes. Configurando Modo AP Local...");
        atualizarOled("Modo AP Ativo", "SSID: Gestor_Kiira", "IP: 192.168.4.1");
    }

    // Mapeamento de Rotas
    server.on("/", handleRoot);
    server.on("/video", handleVideo);
    server.on("/capturar_agora", handleCapturarAgora);
    server.on("/ver", handleVerFoto);
    server.on("/deletar", handleDeletarFoto);
    server.on("/api/data", handleApiData);
    server.on("/action_reset", handleReset);
    
    server.begin();
    adicionarLog("Servidor HTTP ativo e blindado na porta 8080.");
}

void loop() {
    server.handleClient();

    if (WiFi.status() == WL_CONNECTED) {
        if (!mqttClient.connected()) reconectarMQTT();
        mqttClient.loop();
    }

    static unsigned long ultimaTelemetria = 0;
    if (millis() - ultimaTelemetria > 5000) {
        ultimaTelemetria = millis();
        lerSensorHDC();
        
        if (WiFi.status() == WL_CONNECTED && mqttClient.connected()) {
            String topicoClima = String(MQTT_USER) + "/feeds/clima";
            String topicoUmid = String(MQTT_USER) + "/feeds/umidade";
            mqttClient.publish(topicoClima.c_str(), String(temp_local, 2).c_str());
            mqttClient.publish(topicoUmid.c_str(), String(umid_local, 2).c_str());
        }
        
        String ipExibicao = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "192.168.4.1";
        atualizarOled(ipExibicao, "T: " + String(temp_local, 1) + "C U: " + String(umid_local, 1) + "%", "Status: " + status_local);
    }

    if (disparar_reset) {
        disparar_reset = false;
        status_local = "RESET TI";
        adicionarLog("Reset manual acionado via Botão Físico!");
        atualizarOled("SISTEMA: RESET", "MODO EMERGENCY", "CIRCUITO ABERTO");
        digitalWrite(PIN_RELE, LOW);
        delay(5000);
        digitalWrite(PIN_RELE, HIGH);
        status_local = "ONLINE";
    }
}
