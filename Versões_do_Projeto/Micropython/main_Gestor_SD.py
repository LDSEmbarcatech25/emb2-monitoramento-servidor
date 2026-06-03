# =============================================================================
# RESIDÊNCIA TIC37 - EMBARCATECH
# PROJETO: MONITORIZAÇÃO REMOTA (KiiRA v2.0 - TELEMETRIA DUPLA ADAFRUIT)
# =============================================================================

import machine
import time
import network
import uasyncio as asyncio
import random
import usocket as socket
import ustruct as struct
import uos
from ssd1306 import SSD1306_I2C

try:
    import camera
    CAMERA_DISPONIVEL = True
except ImportError:
    CAMERA_DISPONIVEL = False

historico_logs = []
contador_fotos = 0  

def log_sistema(texto):
    global historico_logs
    segundos_ativos = time.ticks_ms() // 1000
    mensagem = f"[{segundos_ativos}s] {texto}"
    print(mensagem)
    
    historico_logs.append(mensagem)
    if len(historico_logs) > 5:
        historico_logs.pop(0)

# =============================================================================
# 1. OPÇÕES DE CONEXÃO À REDE E FEEDS DEDICADOS
# =============================================================================
LISTA_WIFI = [
    {"ssid": "ITSelf", "pass": "code2020"},       
    {"ssid": "IFCE Alunos", "pass": ""},         
    {"ssid": "", "pass": ""}                     
]

ADAFRUIT_USER = "rafaelbrandaorb"
ADAFRUIT_KEY = "aio_pkac63za0hDRftR2ayLgkrsvb7sl"

MQTT_BROKER = "io.adafruit.com"
MQTT_PORT = 1883
CLIENT_ID = f"kiira_{random.randint(10, 99)}" 

# Definição dos canais separados para alimentar os blocos do painel
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
sd_montado = False

i2c_lock = asyncio.Lock()

def tratar_botao_local(pino):
    global disparar_reset, ultimo_clique
    agora = time.ticks_ms()
    if time.ticks_diff(agora, ultimo_clique) > 300:
        ultimo_clique = agora
        log_sistema("Reset manual acionado via Botão Físico!")
        disparar_reset = True

botao_local.irq(handler=tratar_botao_local, trigger=machine.Pin.IRQ_FALLING)

# =============================================================================
# 4. INTERFACE DE HARDWARE, CARTÃO SDMMC E DISPLAY
# =============================================================================
def inicializar_hardware():
    global i2c_global, oled, hardware_ok, sd_montado
    
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

    try:
        sd = machine.SDCard(slot=1, width=1, clk=machine.Pin(39), cmd=machine.Pin(38), d0=machine.Pin(40))
        uos.mount(sd, "/sd")
        sd_montado = True
        log_sistema("Armazenamento SDMMC acoplado em '/sd' (Pronto para datasets/logs).")
    except Exception as e:
        sd_montado = False
        log_sistema(f"Cartão SD ausente ou falha de montagem no barramento SDMMC: {e}")

    if CAMERA_DISPONIVEL:
        try:
            camera.init(0, format=camera.JPEG, framesize=camera.FRAME_CIF)
            camera.quality(16) 
            log_sistema("Módulo óptico ativo e focado.")
        except Exception as e:
            log_sistema(f"Falha física na inicialização da câmera: {e}")
    else:
        log_sistema("Firmware sem suporte nativo à câmera. Modo óptico travado.")

def salvar_foto_no_sd(dados_foto):
    global contador_fotos
    if not sd_montado or dados_foto is None:
        return False
    try:
        contador_fotos += 1
        caminho_arquivo = f"/sd/cam_{contador_fotos}.jpg"
        with open(caminho_arquivo, "wb") as f:
            f.write(dados_foto)
        log_sistema(f"Foto salva localmente: {caminho_arquivo} ({len(dados_foto)} bytes)")
        return True
    except Exception as e:
        log_sistema(f"Erro ao gravar imagem no SDMMC: {e}")
        return False

async def atualizar_oled_seguro(linha1, line2, linha3):
    if hardware_ok and oled is not None:
        async with i2c_lock:
            try:
                oled.fill(0)  
                oled.text("Gestor_Kiira", 5, 0)
                oled.text("----------------", 0, 10)
                oled.text(linha1, 0, 25)
                oled.text(line2, 0, 40)
                oled.text(linha3, 0, 55)
                oled.show()  
            except Exception:
                pass

# =============================================================================
# 5. PROTOCOLO MQTT DIRECT SOCKET
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
            log_sistema("AÇÃO CRÍTICA: Interrompendo energia do Rack...")
            rele_reset.value(0)  
            await asyncio.sleep(5)  
            
            log_sistema("AÇÃO CRÍTICA: Restabelecendo energia do circuito.")
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
                    except Exception as e:
                        log_sistema(f"Sensor I2C temporariamente ocupado: {e}")
                
                # ENVIO DUPLO ATUALIZADO PARA ENVIAR AS DUAS MÉTRICAS DE FORMA INDEPENDENTE
                if sock_global:
                    # 1. Envia Temperatura para o bloco de clima/temperatura
                    payload_temp = f"{temp_local:.2f}"
                    mqtt_publicar_telemetria(TOPIC_TEMPERATURA, payload_temp.encode())
                    await asyncio.sleep_ms(300) # Evita colisões no buffer do socket
                    
                    # 2. Envia Umidade para o bloco novo de umidade
                    payload_umid = f"{umid_local:.2f}"
                    mqtt_publicar_telemetria(TOPIC_UMIDADE, payload_umid.encode())
                
                if CAMERA_DISPONIVEL and sd_montado:
                    try:
                        foto = camera.capture()
                        if foto:
                            salvar_foto_no_sd(foto)
                            del foto
                    except:
                        pass
                
                await atualizar_oled_seguro(f"IP:{meu_ip}", f"T:{temp_local:.1f}C U:{umid_local:.1f}%", f"Status: {status_local}")
            
        except Exception as e:
            log_sistema(f"Exceção no processamento do clima: {e}")
            
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
            log_sistema("[NUVEM] Conexão com Adafruit perdida. Mantendo operação local.")
            
        await asyncio.sleep_ms(200)

# =============================================================================
# 7. TEMPLATE HTML DO DASHBOARD LOCAL
# =============================================================================
HTML_TEMPLATE = """HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n
<!DOCTYPE html>
<html>
<head>
    <title>KiiRA v2.0 - Painel Operacional</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }}
        h2 {{ color: #38bdf8; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 1px; }}
        .sub {{ color: #94a3b8; font-size: 14px; margin-bottom: 25px; }}
        .container {{ display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; max-width: 900px; width:100%; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; width: 260px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .card-video {{ width: 100%; max-width: 500px; }}
        .card-serial {{ width: 100%; max-width: 800px; background: #020617; border-color: #1e293b; align-items: flex-start; justify-content: flex-start; }}
        .val {{ font-size: 36px; font-weight: bold; color: #f1f5f9; margin-top: 10px; }}
        .unit {{ font-size: 18px; color: #38bdf8; }}
        .status {{ padding: 6px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; text-transform: uppercase; margin-top: 10px; margin-bottom: 15px; }}
        .online {{ background: #065f46; color: #34d399; }}
        .resetting {{ background: #991b1b; color: #fca5a5; }}
        .btn {{ background: #e11d48; color: white; border: none; padding: 14px 28px; font-size: 14px; font-weight: bold; border-radius: 8px; cursor: pointer; transition: 0.2s; text-decoration: none; text-align: center; width: 80%; display: block; margin-top: 5px; }}
        .btn:hover {{ background: #be123c; box-shadow: 0 0 15px rgba(225,29,72,0.4); }}
        pre {{ margin: 10px 0 0 0; color: #4ade80; font-family: monospace; font-size: 12px; line-height: 1.5; background: #020617; width: 100%; overflow-x: auto; white-space: pre-wrap; }}
        img {{ width: 100%; border-radius: 8px; border: 1px solid #334155; }}
    </style>
</head>
<body>
    <h2>KiiRA v2.0</h2>
    <div class="sub">Centro de Controle Operacional de TI - Monitorização de Infraestrutura</div>
    <div class="container">
        <div class="card card-video">
            <h3 style="margin:0 0 10px 0; color:#94a3b8;">Monitoramento de Vídeo Local</h3>
            {}
            <a href="/capturar_agora" class="btn" style="background:#0284c7; margin-top:15px;">SALVAR FOTO LOCAL NO SD</a>
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
        
        <div class="card card-serial">
            <span style="color:#38bdf8; font-weight:bold; font-size: 14px; text-transform: uppercase;">Monitor Serial Web (Live Log)</span>
            <pre>{}</pre>
        </div>
    </div>
    <script>
        if (!document.getElementById("video_feed")) {
            setTimeout(function(){{ window.location.reload(); }}, 5000);
        }
    </script>
</body>
</html>
"""

# =============================================================================
# WEB SERVER: DASHBOARD E MONITOR LOCAL
# =============================================================================
async def loop_servidor_video():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', 8080)) 
    server_socket.listen(1) 
    server_socket.setblocking(False)
    
    log_sistema("Servidor HTTP do Dashboard ativo na porta 8080.")

    while True:
        client_sock = None
        try:
            await asyncio.sleep_ms(20) 
            try:
                client_sock, addr = server_socket.accept()
            except OSError:
                continue 

            client_sock.settimeout(1.5)
            requisicao = client_sock.recv(512).decode()
            
            if "GET /video" in requisicao:
                if not CAMERA_DISPONIVEL:
                    client_sock.close()
                    continue
                client_sock.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
                )
                while True: 
                    try:
                        quadro = camera.capture()
                        if quadro:
                            client_sock.write(b"--frame\r\n")
                            client_sock.write(b"Content-Type: image/jpeg\r\n")
                            client_sock.write(f"Content-Length: {len(quadro)}\r\n\r\n".encode())
                            client_sock.write(quadro)
                            client_sock.write(b"\r\n")
                            del quadro 
                    except Exception:
                        break
                    await asyncio.sleep_ms(150) 
                client_sock.close()
                
            elif "GET / " in requisicao or "GET /index" in requisicao:
                if CAMERA_DISPONIVEL:
                    status_sd_txt = " (SDMMC Pronto)" if sd_montado else " (SDMMC Erro/Ausente)"
                    img_tag = f"<img id='video_feed' src='http://{meu_ip}:8080/video'><p style='color:#34d399; font-size:12px; margin-top:5px;'>Feed ativo {status_sd_txt}</p>"
                else:
                    img_tag = "<p style='color:#94a3b8; font-size:13px;'>Módulo óptico desativado no firmware.</p>"
                    if sd_montado:
                        img_tag += "<p style='color:#34d399; font-size:12px;'>Cartão SDMMC montado e pronto para Machine Learning em /sd.</p>"
                    else:
                        img_tag += "<p style='color:#ef4444; font-size:12px;'>Cartão SDMMC desconectado ou em formato incompatível.</p>"
                    
                classe_status = 'online' if status_local == 'ONLINE' else 'resetting'
                texto_serial = "\n".join(historico_logs)
                
                html = HTML_TEMPLATE.format(img_tag, float(temp_local), float(umid_local), classe_status, status_local, texto_serial)
                client_sock.write(html.encode('utf-8'))
                client_sock.close()
                
            elif "GET /capturar_agora" in requisicao:
                if CAMERA_DISPONIVEL and sd_montado:
                    try:
                        foto = camera.capture()
                        if foto:
                            salvar_foto_no_sd(foto)
                            del foto
                    except:
                        pass
                client_sock.write(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
                client_sock.close()
                
            elif "GET /action_reset" in requisicao:
                global disparar_reset
                log_sistema("Comando recebido: Clique de Reset no Dashboard Local.")
                disparar_reset = True
                
                client_sock.write(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
                client_sock.close()
            else:
                client_sock.close()

        except Exception:
            if client_sock:
                try:
                    client_sock.close()
                except:
                    pass

# =============================================================================
# 8. ORQUESTRAÇÃO GERAL
# =============================================================================
async def main():
    global meu_ip, sock_global
    inicializar_hardware()
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    conectado = False
    
    for indice, rede in enumerate(LISTA_WIFI, start=1):
        if not rede['ssid']: 
            continue
            
        log_sistema(f"Escaneando Wi-Fi -> Tentando Opção {indice}: {rede['ssid']}...")
        await atualizar_oled_seguro(f"Conectando W-Fi...", f"Opcao {indice}:", rede['ssid'])
        
        wlan.connect(rede['ssid'], rede['pass'])
        
        timeout = 0
        while not wlan.isconnected() and timeout < 14:
            await asyncio.sleep(0.5)
            timeout += 1
            
        if wlan.isconnected():
            meu_ip = wlan.ifconfig()[0]
            log_sistema(f"Wi-Fi autenticado com sucesso! Endereço IP: {meu_ip}")
            conectado = True
            break
        else:
            log_sistema(f"Tempo limite excedido para a rede: {rede['ssid']}")
            wlan.disconnect()

    if not conectado:
        log_sistema("Nenhuma rede Wi-Fi ao alcance. Ativando Modo de Emergência AP...")
        await atualizar_oled_seguro("SEM WI-FI!", "ATIVANDO MODO AP", "AGUARDE...")
        wlan.active(False) 
        await asyncio.sleep(0.5)
        
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid="Gestor_Kiira", password="kiira2026", authmode=network.AUTH_WPA2_PSK)
        await asyncio.sleep(1.5) 
        
        config_ip = ap.ifconfig()
        meu_ip = "192.168.4.1" if config_ip[0] == '0.0.0.0' else config_ip[0]
        log_sistema("Rede Hotspot local ativa. SSID: Gestor_Kiira")
    else:
        await atualizar_oled_seguro("Wi-Fi: OK", f"IP: {meu_ip}", "Adafruit Conn...")
        try:
            if mqtt_conectar_broker():
                mqtt_inscrever_topico(TOPIC_COMANDOS)
                log_sistema("Sincronização bem-sucedida com a Nuvem Adafruit IO.")
                await atualizar_oled_seguro(f"IP: {meu_ip}", "ADAFRUIT: ATIVO", "SISTEMA ONLINE")
            else:
                log_sistema("Conexão MQTT recusada. Operando apenas em modo local.")
        except Exception as e:
            log_sistema(f"Falha de rota para o broker: {e}")

    await asyncio.gather(
        loop_telemetria_clima(),
        loop_escuta_broker(),
        loop_servidor_video(),
        loop_gerenciador_reset()
    )

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n[SISTEMA] Execução interrompida.")