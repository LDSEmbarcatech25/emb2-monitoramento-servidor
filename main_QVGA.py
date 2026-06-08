# =============================================================================
# RESIDÊNCIA TIC37 - EMBARCATECH
# PROJETO: DISPOSITIVO IoT PARA MONITORAMENTO DE SERVIDOR E INFRAESTRUTURA DE REDE
# VERÇÃO: 2.1 (Estabilizada e Otimizada)
# =============================================================================
import machine
import time
import network
import uasyncio as asyncio
import random
import usocket as socket
import ustruct as struct
import os
import gc  # Gerenciamento estrito de memória RAM
from ssd1306 import SSD1306_I2C
from camera import Camera, GrabMode, PixelFormat, FrameSize

historico_logs = []
LIMITE_FOTOS = 10  # Limite de fotos na Flash

def log_sistema(texto):
    global historico_logs
    segundos_ativos = time.ticks_ms() // 1000
    mensagem = f"[{segundos_ativos}s] {texto}"
    print(mensagem)
    
    historico_logs.append(mensagem)
    if len(historico_logs) > 5:
        historico_logs.pop(0)

# --- CONFIGURAÇÃO AUTOMÁTICA DO LITTLEFS ---
print("[SISTEMA] Checando integridade do sistema de arquivos interno...")
try:
    if "fotos" not in os.listdir("/"):
        os.mkdir("/fotos")
        log_sistema("Pasta /fotos criada com sucesso no LittleFS interno.")
except Exception as e:
    print(f"[ERRO LITTLEFS] Falha ao gerenciar diretório: {e}")

# =============================================================================
# 1. OPÇÕES DE CONEXÃO À REDE E FEEDS DA ADAFRUIT
# =============================================================================
LISTA_WIFI = [
    {"ssid": "ITSelf", "pass": "code2020"},       
    {"ssid": "SUA_REDE_RESERVA", "pass": "SUA_SENHA"},         
    {"ssid": "", "pass": ""}                     
]

ADAFRUIT_USER = "rafaelbrandaorb"
ADAFRUIT_KEY = "aio_pkac63za0hDRftR2ayLgkrsvb7sl"

MQTT_BROKER = "io.adafruit.com"
MQTT_PORT = 1883
CLIENT_ID = f"kiira_{random.randint(10, 99)}" 

TOPIC_TEMPERATURA = f"{ADAFRUIT_USER}/feeds/clima".encode()
TOPIC_UMIDADE = f"{ADAFRUIT_USER}/feeds/umidade".encode()
TOPIC_COMANDOS = f"{ADAFRUIT_USER}/feeds/comandos".encode()

# =============================================================================
# 2. DEFINIÇÃO DE PINOS DA PLACA KiiRA v2.0
# =============================================================================
PIN_RELE = 48  
PIN_BOTAO = 46  
PIN_SDA = 14  
PIN_SCL = 21  

rele_reset = machine.Pin(PIN_RELE, machine.Pin.OUT)
rele_reset.value(1)  

botao_local = machine.Pin(PIN_BOTAO, machine.Pin.IN, machine.Pin.PULL_UP)

sock_global = None
pid_packet = 0
temp_local = 0.0
umid_local = 0.0
status_local = "ONLINE"
disparar_reset = False  
ultimo_clique = 0      
meu_ip = "0.0.0.0"

i2c_global = None
oled = None
hdc_endereco = 0x40  
hardware_ok = False
cam_obj = None  # Objeto global da câmera

i2c_lock = asyncio.Lock()
cam_lock = asyncio.Lock() # Lock para evitar conflito entre stream e captura de foto

def tratar_botao_local(pino):
    global disparar_reset, ultimo_clique
    agora = time.ticks_ms()
    if time.ticks_diff(agora, ultimo_clique) > 300:
        ultimo_clique = agora # CORRIGIDO: Removido 'grandmother' inexistente
        log_sistema("Reset manual acionado via Botão Físico!")
        disparar_reset = True

botao_local.irq(handler=tratar_botao_local, trigger=machine.Pin.IRQ_FALLING)

# =============================================================================
# 4. INTERFACE DE HARDWARE E INICIALIZAÇÃO DA CÂMERA
# =============================================================================
def inicializar_hardware():
    global i2c_global, oled, hardware_ok, cam_obj
    
    gc.collect()
    
    # Inicialização do Barramento I2C
    try:
        i2c_global = machine.I2C(0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA), freq=100000)
        log_sistema("Barramento I2C físico unificado a 100kHz.")
        try:
            oled = SSD1306_I2C(128, 64, i2c_global)
            hardware_ok = True
            log_sistema("Periféricos I2C mapeados com sucesso.")
        except Exception as e:
            log_sistema(f"Falha ao acoplar display: {e}")
    except Exception as e:
        log_sistema(f"Falha ao erguer barramento elemental: {e}")

    # Inicialização da Câmera
    try:
        cam_obj = Camera(
            data_pins=[11, 9, 8, 10, 12, 18, 17, 16],
            pclk_pin=13, vsync_pin=6, href_pin=7, sda_pin=4, scl_pin=5, xclk_pin=15,
            xclk_freq=20_000_000,
            pixel_format=PixelFormat.JPEG,  
            frame_size=FrameSize.QVGA,       
            grab_mode=GrabMode.LATEST,
        )
        log_sistema("Módulo óptico OV5640 ativo via Classe Objeto (QVGA).")
    except Exception as e:
        cam_obj = None
        log_sistema(f"Falha crítica na inicialização da câmera: {e}")

async def atualizar_oled_seguro(linha1, linha2, linha3):
    if hardware_ok and oled is not None:
        async with i2c_lock:
            try:
                oled.fill(0)  
                oled.text("Gestor_Kiira", 5, 0)
                oled.text("----------------", 0, 10)
                oled.text(linha1, 0, 25)
                oled.text(linha2, 0, 40)
                oled.text(linha3, 0, 55)
                oled.show()  
            except Exception:
                pass

# =============================================================================
# 5. PROTOCOLO MQTT DIRECT SOCKET (ADAFRUIT CLOUD)
# =============================================================================
def mqtt_enviar_str(s):
    global sock_global
    sock_global.write(struct.pack("!H", len(s)))
    sock_global.write(s)

def mqtt_conectar_broker():
    global sock_global
    try:
        addr = socket.getaddrinfo(MQTT_BROKER, MQTT_PORT)[0][-1]
        sock_global = socket.socket()
        sock_global.settimeout(3.0) 
        sock_global.connect(addr)
        
        premsg = bytearray(b"\x00\x04MQTT\x04\xC2\x00\x3C")
        length = len(premsg) + 2 + len(CLIENT_ID) + 2 + len(ADAFRUIT_USER) + 2 + len(ADAFRUIT_KEY)
        
        msg = bytearray([0x10, length])
        sock_global.write(msg)
        sock_global.write(premsg)
        
        mqtt_enviar_str(CLIENT_ID)
        mqtt_enviar_str(ADAFRUIT_USER) 
        mqtt_enviar_str(ADAFRUIT_KEY)
        
        resp = sock_global.read(4)
        if resp and resp[0] == 0x20 and resp[3] == 0:
            sock_global.settimeout(None)
            return True
    except Exception as e:
        log_sistema(f"Falha na handshake com a nuvem: {e}")
    sock_global = None
    return False

def mqtt_inscrever_topico(topico):
    global sock_global, pid_packet
    if not sock_global: return
    try:
        pid_packet += 1
        length = 2 + 2 + len(topico) + 1
        packet = struct.pack("!BBH", 0x82, length, pid_packet)
        sock_global.write(packet)
        sock_global.write(struct.pack("!H", len(topico)))
        sock_global.write(topico)
        sock_global.write(b"\x00") 
        sock_global.read(5)  
    except:
        sock_global = None

def mqtt_publicar_telemetria(topico, msg):
    global sock_global
    if not sock_global: return
    try:
        pkt = bytearray([0x30, 2 + len(topico) + len(msg)])
        sock_global.write(pkt)
        mqtt_enviar_str(topico)
        sock_global.write(msg)
    except:
        sock_global = None

def tratar_comandos_remotos(msg):
    global disparar_reset
    log_sistema(f"Nuvem Adafruit enviou comando: {msg}")
    if "HARD_RESET" in msg or msg == "1":
        disparar_reset = True

# =============================================================================
# 6. ROTINAS ASSÍNCRONAS CONCORRENTES
# =============================================================================
async def loop_gerenciador_reset():
    global disparar_reset, status_local
    while True:
        if disparar_reset:
            disparar_reset = False 
            status_local = "RESET TI"
            await atualizar_oled_seguro("SISTEMA: RESET", "MODO EMERGENCY", "CIRCUITO ABERTO")
            rele_reset.value(0)  
            await asyncio.sleep(5)  
            rele_reset.value(1)  
            status_local = "ONLINE"
            await atualizar_oled_seguro(f"IP: {meu_ip}", f"Temp: {temp_local:.1f} C", f"Status: {status_local}")
        await asyncio.sleep_ms(100)

async def loop_telemetria_clima():
    global temp_local, umid_local
    while True:
        try:
            if status_local == "ONLINE" and hardware_ok and i2c_global is not None:
                async with i2c_lock:
                    try:
                        i2c_global.writeto(hdc_endereco, b'\x00')
                        await asyncio.sleep_ms(40)  
                        dados = i2c_global.readfrom(hdc_endereco, 4)
                        temp_raw = (dados[0] << 8) | dados[1]
                        temp_local = (temp_raw / 65536.0) * 165.0 - 40.0
                        umid_raw = (dados[2] << 8) | dados[3]
                        umid_local = (umid_raw / 65536.0) * 100.0
                    except Exception:
                        pass
                
                if sock_global:
                    mqtt_publicar_telemetria(TOPIC_TEMPERATURA, f"{temp_local:.2f}".encode())
                    await asyncio.sleep_ms(300) 
                    mqtt_publicar_telemetria(TOPIC_UMIDADE, f"{umid_local:.2f}".encode())
                
                await atualizar_oled_seguro(f"IP:{meu_ip}", f"T:{temp_local:.1f}C U:{umid_local:.1f}%", f"Status: {status_local}")
        except Exception as e:
            log_sistema(f"Exceção no clima: {e}")
        await asyncio.sleep(10)

async def loop_escuta_broker():
    global sock_global
    while True:
        try:
            if sock_global:
                sock_global.setblocking(False)
                try:
                    res = sock_global.read(1)
                except OSError:
                    res = None
                if res:
                    sock_global.setblocking(True)
                    if res[0] & 0xF0 == 0x30: 
                        sz = sock_global.read(1)[0]
                        topic_len = struct.unpack("!H", sock_global.read(2))[0]
                        sock_global.read(topic_len) 
                        msg_len = sz - 2 - topic_len
                        mensagem_bruta = sock_global.read(msg_len).decode().strip()
                        tratar_comandos_remotos(mensagem_bruta)
        except Exception:
            sock_global = None
        await asyncio.sleep_ms(200)

# =============================================================================
# 7. TEMPLATE HTML DO DASHBOARD
# =============================================================================
HTML_TEMPLATE = """HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n
<!DOCTYPE html>
<html>
<head>
    <title>Gestor Kiira - Painel Operacional</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }}
        h2 {{ color: #38bdf8; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 1px; }}
        .sub {{ color: #94a3b8; font-size: 14px; margin-bottom: 25px; }}
        .container {{ display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; max-width: 1000px; width:100%; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; width: 280px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .card-video {{ width: 100%; max-width: 440px; }}
        .card-galeria {{ width: 100%; max-width: 440px; }}
        .card-serial {{ width: 100%; max-width: 940px; background: #020617; border-color: #1e293b; align-items: flex-start; justify-content: flex-start; }}
        .val {{ font-size: 36px; font-weight: bold; color: #f1f5f9; margin-top: 10px; }}
        .unit {{ font-size: 18px; color: #38bdf8; }}
        .status {{ padding: 6px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; text-transform: uppercase; margin-top: 10px; margin-bottom: 15px; }}
        .online {{ background: #065f46; color: #34d399; }}
        .resetting {{ background: #991b1b; color: #fca5a5; }}
        .btn {{ background: #e11d48; color: white; border: none; padding: 14px 28px; font-size: 14px; font-weight: bold; border-radius: 8px; cursor: pointer; transition: 0.2s; text-decoration: none; text-align: center; width: 80%; display: block; margin-top: 5px; }}
        pre {{ margin: 10px 0 0 0; color: #4ade80; font-family: monospace; font-size: 12px; line-height: 1.5; background: #020617; width: 100%; overflow-x: auto; white-space: pre-wrap; }}
        img {{ width: 100%; max-height: 260px; object-fit: contain; border-radius: 8px; border: 1px solid #334155; background: #020617; }}
        .lista-arquivos {{ width: 100%; margin-top: 10px; max-height: 210px; overflow-y: auto; }}
        .item-arquivo {{ display: flex; justify-content: space-between; align-items: center; background: #334155; padding: 8px 12px; margin-bottom: 6px; border-radius: 6px; font-size: 14px; }}
        .btn-view {{ background: #38bdf8; color: #0f172a; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; }}
        .btn-del {{ background: #ef4444; color: white; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; margin-left: 5px; }}
    </style>
</head>
<body>
    <h2>Gestor KiiRA 2.0</h2>
    <div class="sub">Centro de Controle Operacional de TI (Armazenamento LittleFS)</div>
    <div class="container">
        
        <div class="card card-video">
            <h3 style="margin:0 0 10px 0; color:#94a3b8;">Monitoramento de Vídeo Local</h3>
            {}
            <a href="/capturar_agora" class="btn" style="background:#10b981; margin-top:15px;">📸 DISPARAR E SALVAR FOTO</a>
        </div>
        
        <div style="display:flex; flex-direction:column; gap:20px;">
            <div class="card">
                <span style="color:#94a3b8; font-weight:500;">Temperatura do Rack</span>
                <div class="val">{:.1f}<span class="unit">°C</span></div>
            </div>
            <div class="card">
                <span style="color:#94a3b8; font-weight:500;">Umidade do Ambiente</span>
                <div class="val">{:.1f}<span class="unit">%</span></div>
            </div>
            <div class="card">
                <span style="color:#94a3b8; font-weight:500;">Status da Placa</span>
                <div class="status {}">{}</div>
                <a href="/action_reset" class="btn">FORÇAR HARD RESET</a>
            </div>
        </div>

        <div class="card card-galeria">
            <h3 style="margin:0 0 10px 0; color:#38bdf8;">Galeria Interna (Flash)</h3>
            <div class="lista-arquivos">
                {}
            </div>
            <a href="/" class="btn" style="background:#475569; margin-top:15px;">🔄 ATUALIZAR LISTA</a>
        </div>
        
        <div class="card card-serial">
            <span style="color:#38bdf8; font-weight:bold; font-size: 14px; text-transform: uppercase;">Monitor Serial Web (Live Log)</span>
            <pre>{}</pre>
        </div>
    </div>
</body>
</html>
"""

# =============================================================================
# 8. WEB SERVER ASSÍNCRONO CORRIGIDO (NÃO TRAVANTE)
# =============================================================================
async def loop_servidor_video():
    global cam_obj
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', 8080)) 
    server_socket.listen(3) 
    server_socket.setblocking(False)
    
    log_sistema("Servidor HTTP ativo na porta 8080.")

    while True:
        client_sock = None
        try:
            await asyncio.sleep_ms(10) # Pausa curta para ceder tempo a outras tarefas
            try:
                client_sock, addr = server_socket.accept()
            except OSError:
                continue 

            client_sock.settimeout(2.0)
            requisicao = client_sock.recv(1024).decode()
            
            gc.collect()
            
            # --- ROTA 1: FLUXO DE VÍDEO (STREAM REAL SEGURO) ---
            if "GET /video" in requisicao:
                if cam_obj is None:
                    client_sock.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                    client_sock.close()
                    continue
                
                client_sock.write(b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n")
                
                # Streaming limitado por requisição para evitar congelamento do uasyncio
                for _ in range(100): # Envia 100 quadros por conexão e fecha de forma limpa (o browser reabre automaticamente)
                    try:
                        async with cam_lock:
                            quadro = cam_obj.capture()  
                        if quadro:
                            client_sock.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(quadro)).encode() + b"\r\n\r\n" + quadro + b"\r\n")
                        
                        if cam_obj: cam_obj.free_buffer()
                        await asyncio.sleep_ms(60) # Taxa fluida dando vazão para o uasyncio rodar outras tarefas
                    except Exception:
                        break
                
                try: client_sock.close()
                except: pass
                
            # --- ROTA 2: HOME DASHBOARD ---
            elif "GET / " in requisicao or "GET /index" in requisicao:
                if cam_obj is not None:
                    img_tag = f"<img id='video_feed' src='http://{meu_ip}:8080/video'><p style='color:#34d399; font-size:12px; margin:5px 0 0 0;'>Transmissão QVGA Ativa (OV5640)</p>"
                else:
                    img_tag = "<p style='color:#94a3b8;'>Câmera offline localmente.</p>"
                    
                classe_status = 'online' if status_local == 'ONLINE' else 'resetting'
                texto_serial = "\n".join(historico_logs)
                
                arquivos = [f for f in os.listdir("/fotos") if f.endswith(".jpg")]
                arquivos.sort()
                
                itens_html = ""
                if not arquivos:
                    itens_html = "<div style='color:#64748b; font-style:italic; text-align:center; padding-top:20px;'>Nenhuma foto salva na Flash.</div>"
                else:
                    for nome_arq in arquivos:
                        itens_html += f"""
                        <div class='item-arquivo'>
                            <span>📂 {nome_arq}</span>
                            <div>
                                <a href='/ver?file={nome_arq}' target='_blank' class='btn-view'>👁️ VER</a>
                                <a href='/deletar?file={nome_arq}' class='btn-del'>🗑️</a>
                            </div>
                        </div>
                        """
                
                html = HTML_TEMPLATE.format(img_tag, float(temp_local), float(umid_local), classe_status, status_local, itens_html, texto_serial)
                client_sock.write(html.encode('utf-8'))
                client_sock.close()
                
            # --- ROTA 3: DISPARADOR DA CÂMERA ---
            elif "GET /capturar_agora" in requisicao:
                if cam_obj is not None:
                    try:
                        gc.collect()
                        arquivos = [f for f in os.listdir("/fotos") if f.endswith(".jpg")]
                        
                        if len(arquivos) >= LIMITE_FOTOS:
                            arquivos.sort()
                            os.remove(f"/fotos/{arquivos[0]}")
                        
                        numeros = [int(f.split('_')[1].split('.')[0]) for f in arquivos if '_' in f]
                        proximo_id = max(numeros) + 1 if numeros else 1
                        
                        async with cam_lock: # Protege o buffer contra o stream simultâneo
                            foto = cam_obj.capture()  
                        if foto: 
                            with open(f"/fotos/foto_{proximo_id}.jpg", "wb") as f:
                                f.write(foto)
                            log_sistema(f"Foto registrada na Flash: foto_{proximo_id}.jpg")
                    except Exception as e: 
                        log_sistema(f"Erro na captura Flash: {e}")
                    finally:
                        if cam_obj: cam_obj.free_buffer()
                        gc.collect()
                        
                client_sock.write(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
                client_sock.close()
                
            # --- ROTA 4: VISUALIZAÇÃO INDIVIDUAL ---
            elif "GET /ver?file=" in requisicao:
                try:
                    nome_arquivo = requisicao.split("file=")[1].split(" ")[0]
                    caminho_completo = f"/fotos/{nome_arquivo}"
                    
                    tamanho = os.stat(caminho_completo)[6]
                    header = b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(tamanho).encode() + b"\r\n\r\n"
                    client_sock.write(header)
                    
                    with open(caminho_completo, "rb") as f:
                        while chunk := f.read(1024): # Chunk reduzido para estabilidade de RAM
                            client_sock.write(chunk)
                except:
                    client_sock.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                client_sock.close()

            # --- ROTA 5: EXCLUSÃO DE FOTO ---
            elif "GET /deletar?file=" in requisicao:
                try:
                    nome_arquivo = requisicao.split("file=")[1].split(" ")[0]
                    os.remove(f"/fotos/{nome_arquivo}")
                    log_sistema(f"Removido da Flash: {nome_arquivo}")
                except: 
                    pass
                client_sock.write(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
                client_sock.close()
                
            # --- ROTA 6: RESET DO RELÉ ---
            elif "GET /action_reset" in requisicao:
                global disparar_reset
                disparar_reset = True
                client_sock.write(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
                client_sock.close()
            else:
                client_sock.close()

        except Exception as e:
            if client_sock:
                try: client_sock.close()
                except: pass

# =============================================================================
# 9. ORQUESTRAÇÃO GERAL
# =============================================================================
async def main():
    global meu_ip, sock_global
    inicializar_hardware()
    
    wlan = network.WLAN(network.STA_IF)
    conectado = False
    
    redes_validas = [r for r in LISTA_WIFI if r.get('ssid') and r['ssid'] != ""]
    
    if redes_validas:
        wlan.active(True)
        for indice, rede in enumerate(redes_validas, start=1):
            log_sistema(f"Tentando rede {indice}: {rede['ssid']}...")
            await atualizar_oled_seguro("Conectando Wi-Fi", f"Tentando {indice}:", rede['ssid'])
            wlan.connect(rede['ssid'], rede['pass'])
            
            timeout = 0
            while not wlan.isconnected() and timeout < 14:
                await asyncio.sleep(0.5)
                timeout += 1
                
            if wlan.isconnected():
                meu_ip = wlan.ifconfig()[0]
                log_sistema(f"Conectado com IP: {meu_ip}")
                conectado = True
                break
            else:
                wlan.disconnect()

    if not conectado:
        log_sistema("Roteadores ausentes. Configurando Modo AP Local...")
        await atualizar_oled_seguro("SEM WI-FI!", "INICIANDO AP...", "AGUARDE...")
        
        wlan.active(False)
        await asyncio.sleep(0.5) 
        
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid="Gestor_Kiira", password="kiira2026")
        
        await asyncio.sleep(1.0) 
        meu_ip = "192.168.4.1"
        log_sistema("Modo AP Operacional. SSID: Gestor_Kiira | IP: 192.168.4.1")
        await atualizar_oled_seguro("REDE: GESTOR_KIIRA", "PAINEL WEB PRONTO", f"IP: {meu_ip}")
    else:
        await atualizar_oled_seguro("Wi-Fi: OK", f"IP: {meu_ip}", "Adafruit Conn...")
        try:
            if mqtt_conectar_broker():
                mqtt_inscrever_topico(TOPIC_COMANDOS)
                log_sistema("Sincronizado com Adafruit.")
                await atualizar_oled_seguro(f"IP: {meu_ip}", "ADAFRUIT: ATIVO", "SISTEMA ONLINE")
        except:
            log_sistema("Aviso: Nuvem Adafruit indisponível no momento.")

    # Inicializa os loops concorrentes
    await asyncio.gather(
        loop_telemetria_clima(),
        loop_escuta_broker(),
        loop_servidor_video(),
        loop_gerenciador_reset()
    )

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n[SISTEMA] Interrompido pelo usuário.")
