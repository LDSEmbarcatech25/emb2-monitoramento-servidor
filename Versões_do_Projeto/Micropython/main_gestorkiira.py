# =============================================================================
# RESIDÊNCIA TIC18 - EMBARCATECH
# PROJETO: MONITORIZAÇÃO REMOTA (KiiRA v2.0 - COM RESET LOCAL E REMOTO)
# =============================================================================

import machine
import time
import network
import uasyncio as asyncio
import random
import usocket as socket
import ustruct as struct
from ssd1306 import SSD1306_I2C

try:
    import camera
    CAMERA_DISPONIVEL = True
except ImportError:
    CAMERA_DISPONIVEL = False
    print("[AVISO SISTEMA] Firmware sem módulo 'camera'. Modo de vídeo desativado.")

# =============================================================================
# 1. CONFIGURAÇÕES, CREDENCIAIS E DIRETIVAS DE REDE (ADAFRUIT IO)
# =============================================================================
WIFI_SSID = "ITSelf"
WIFI_PASS = "code2020"

ADAFRUIT_USER = "rafaelbrandaorb"
ADAFRUIT_KEY  = "aio_sDqy66WuIbnXlWMtPoWfv9CsRiJW"

MQTT_BROKER = "io.adafruit.com"
MQTT_PORT   = 1883
CLIENT_ID   = f"kiira_{random.randint(10, 99)}" 

TOPIC_TELEMETRIA = f"{ADAFRUIT_USER}/feeds/clima".encode()
TOPIC_COMANDOS   = f"{ADAFRUIT_USER}/feeds/comandos".encode()

# =============================================================================
# 2. DEFINIÇÃO DE PINOS DA PLACA KiiRA v2.0
# =============================================================================
PIN_RELE  = 48  
PIN_BOTAO = 46  # <-- Novo pino do botão físico de Reset Local
PIN_SDA   = 14  
PIN_SCL   = 21  

rele_reset = machine.Pin(PIN_RELE, machine.Pin.OUT)
rele_reset.value(1)  

# Configura o botão com resistor de Pull-Up interno (fica em 1, vai para 0 ao apertar)
botao_local = machine.Pin(PIN_BOTAO, machine.Pin.IN, machine.Pin.PULL_UP)

sock_global     = None
pid_packet      = 0
temp_local      = 0.0
umid_local      = 0.0
status_local    = "ONLINE"
disparar_reset  = False  
ultimo_clique   = 0      # Guarda o tempo do último clique para o debounce técnico
meu_ip          = "0.0.0.0"

i2c_global   = None
oled         = None
hdc_endereco = 0x40  
hardware_ok  = False

i2c_lock = asyncio.Lock()

# =============================================================================
# 3. INTERRUPÇÃO DE HARDWARE (RESET MANUAL VIA BOTÃO FÍSICO)
# =============================================================================
def tratar_botao_local(pino):
    """Esta função roda instantaneamente no chip quando o botão é pressionado"""
    global disparar_reset, ultimo_clique
    agora = time.ticks_ms()
    
    # Filtro Debounce: ignora ruídos elétricos num intervalo menor que 300ms
    if time.ticks_diff(agora, ultimo_clique) > 300:
        ultimo_clique = agora
        print("\n[BOTÃO LOCAL] Botão físico pressionado na GPIO 46! Disparando Reset...")
        disparar_reset = True

# Ativa o detector do botão para disparar quando o pino cair para nível baixo (FALLING)
botao_local.irq(handler=tratar_botao_local, trigger=machine.Pin.IRQ_FALLING)

# =============================================================================
# 4. INTERFACE DE HARDWARE E DISPLAY
# =============================================================================
def inicializar_hardware():
    global i2c_global, oled, hardware_ok
    try:
        i2c_global = machine.I2C(0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA), freq=100000)
        print("[HARDWARE] Barramento I2C físico unificado a 100kHz.")
        try:
            oled = SSD1306_I2C(128, 64, i2c_global)
            hardware_ok = True
            print("[HARDWARE] Periféricos I2C mapeados com sucesso.")
        except Exception as e:
            print("[ERRO HARDWARE] Falha ao acoplar display:", e)
    except Exception as e:
        print("[ERRO CRÍTICO] Falha ao erguer barramento elemental:", e)

    if CAMERA_DISPONIVEL:
        try:
            camera.init(0, format=camera.JPEG, framesize=camera.FRAME_QVGA)
            camera.quality(12) 
            print("[HARDWARE] Subsistema óptico configurado para Streaming Local.")
        except Exception as e:
            print("[ERRO HARDWARE] Falha ao inicializar registradores da câmera:", e)

async def atualizar_oled_seguro(linha1, line2, linha3):
    if hardware_ok and oled is not None:
        async with i2c_lock:
            try:
                oled.fill(0)  
                oled.text("KiiRA v2.0 - TI", 5, 0)
                oled.text("----------------", 0, 10)
                oled.text(linha1, 0, 25)
                oled.text(line2, 0, 40)
                oled.text(linha3, 0, 55)
                oled.show()  
            except Exception as e:
                pass

# =============================================================================
# 5. IMPLEMENTAÇÃO DIRETA DO PROTOCOLO MQTT (SOCKET)
# =============================================================================
def mqtt_enviar_str(s):
    global sock_global
    sock_global.write(struct.pack("!H", len(s)))
    sock_global.write(s)

def mqtt_conectar_broker():
    global sock_global
    addr = socket.getaddrinfo(MQTT_BROKER, MQTT_PORT)[0][-1]
    sock_global = socket.socket()
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
        return True
    return False

def mqtt_inscrever_topico(topico):
    global sock_global, pid_packet
    pid_packet += 1
    length = 2 + 2 + len(topico) + 1
    packet = struct.pack("!BBH", 0x82, length, pid_packet)
    sock_global.write(packet)
    sock_global.write(struct.pack("!H", len(topico)))
    sock_global.write(topico)
    sock_global.write(b"\x00") 
    sock_global.read(5) 

def mqtt_publicar_telemetria(topico, msg):
    global sock_global
    pkt = bytearray([0x30, 2 + len(topico) + len(msg)])
    sock_global.write(pkt)
    mqtt_enviar_str(topico)
    sock_global.write(msg)

def tratar_comandos_remotos(msg):
    global disparar_reset
    print(f"\n[ADAFRUIT IO] Comando recebido: {msg}")
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
            
            # Atualização imediata do ecrã com a origem do acionamento
            await atualizar_oled_seguro("SISTEMA: RESET", "BOTAO / NUVEM", "CIRCUITO ABERTO")
            print("[RELÉ] Abrindo contacto mecânico (Desligando Rack)...")
            rele_reset.value(0)  
            await asyncio.sleep(5)  
            
            print("[RELÉ] Restabelecendo energia (Ligando Rack)...")
            rele_reset.value(1)  
            status_local = "ONLINE"
            await atualizar_oled_seguro(f"IP: {meu_ip}", f"Temp: {temp_local:.1f} C", f"Status: {status_local}")
            
        await asyncio.sleep_ms(100)

async def loop_telemetria_clima():
    while True:
        try:
            if status_local == "ONLINE":
                if hardware_ok and i2c_global is not None:
                    async with i2c_lock:
                        i2c_global.writeto(hdc_endereco, b'\x00')
                        await asyncio.sleep_ms(30)  
                        dados = i2c_global.readfrom(hdc_endereco, 4)
                        
                        temp_raw = (dados[0] << 8) | dados[1]
                        temp_local = (temp_raw / 65536.0) * 165.0 - 40.0
                        
                        umid_raw = (dados[2] << 8) | dados[3]
                        umid_local = (umid_raw / 65536.0) * 100.0
                
                payload = f"{temp_local:.2f}"
                try:
                    mqtt_publicar_telemetria(TOPIC_TELEMETRIA, payload.encode())
                    print(f"[TELEMETRIA] Enviado para Adafruit: {payload} C")
                except:
                    pass # Se a internet cair, o loop local de clima não quebra o sistema
                
                await atualizar_oled_seguro(f"IP:{meu_ip}", f"T:{temp_local:.1f}C U:{umid_local:.1f}%", f"Status: {status_local}")
            
        except Exception as e:
            print("[ERRO TELEMETRIA] Falha no ciclo de leitura:", e)
            
        await asyncio.sleep(20)

async def loop_escuta_broker():
    global sock_global
    while True:
        try:
            if sock_global:
                sock_global.setblocking(False)
                res = sock_global.read(1)
                sock_global.setblocking(True)
                
                if res and res[0] & 0xF0 == 0x30: 
                    sz = sock_global.read(1)[0]
                    topic_len = struct.unpack("!H", sock_global.read(2))[0]
                    sock_global.read(topic_len) 
                    
                    msg_len = sz - 2 - topic_len
                    mensagem_bruta = sock_global.read(msg_len).decode().strip()
                    tratar_comandos_remotos(mensagem_bruta)
                
        except Exception:
            pass
        await asyncio.sleep_ms(150)

# =============================================================================
# 7. SERVIDOR DE VÍDEO HTTP (STREAMING LOCAL)
# =============================================================================
async def loop_servidor_video():
    if not CAMERA_DISPONIVEL:
        return

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', 8080))
    server_socket.listen(1)
    server_socket.setblocking(False)
    
    print("[CÂMERA] Servidor de Vídeo ativo na porta 8080.")

    while True:
        client_sock = None
        try:
            await asyncio.sleep_ms(50)
            try:
                client_sock, addr = server_socket.accept()
            except OSError:
                continue 

            client_sock.setblocking(True)
            client_sock.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
            )

            while status_local == "ONLINE":
                quadro = camera.capture()
                if quadro:
                    client_sock.write(b"--frame\r\n")
                    client_sock.write(b"Content-Type: image/jpeg\r\n")
                    client_sock.write(f"Content-Length: {len(quadro)}\r\n\r\n".encode())
                    client_sock.write(quadro)
                    client_sock.write(b"\r\n")
                    del quadro 
                await asyncio.sleep_ms(80)

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
    await atualizar_oled_seguro("Iniciando...", "Botao Gpio46: OK", "")
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    await asyncio.sleep(1) 
    wlan.active(True)
    await asyncio.sleep(1)
    
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print(f"[REDE] Conectando ao ponto de acesso: {WIFI_SSID}")
    
    timeout_rede = 0
    while not wlan.isconnected() and timeout_rede < 20: # Timeout menor para não travar o botão local se o Wi-Fi sumir
        await asyncio.sleep(0.5)
        print(".", end="")
        timeout_rede += 1
        
    if wlan.isconnected():
        meu_ip = wlan.ifconfig()[0]
        print(f"\n[REDE] Wi-Fi Conectado! IP: {meu_ip}")
        await atualizar_oled_seguro("Wi-Fi: OK", f"IP: {meu_ip}", "Adafruit Conn...")
        
        print(f"[SISTEMA] Autenticando com Adafruit IO ({ADAFRUIT_USER})...")
        try:
            if mqtt_conectar_broker():
                mqtt_inscrever_topico(TOPIC_COMANDOS)
                print("[SISTEMA] Conectado à Adafruit com sucesso!")
                await atualizar_oled_seguro(f"IP: {meu_ip}", "ADAFRUIT: ATIVO", "KiiRA ONLINE")
        except Exception as e:
            print("[AVISO REDE] Servidor Adafruit indisponível. Operando em modo de contingência:", e)
            await atualizar_oled_seguro(f"IP: {meu_ip}", "MODO LOCAL ONLY", "KiiRA ONLINE")
    else:
        print("\n[AVISO REDE] Wi-Fi não encontrado. Iniciando sistema apenas em modo Local.")
        await atualizar_oled_seguro("SEM WI-FI", "MODO MANUAL", "KiiRA ONLINE")

    # Dispara todas as tarefas. O botão físico funcionará mesmo que o Wi-Fi falhe.
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