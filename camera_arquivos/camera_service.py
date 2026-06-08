from camera import Camera, GrabMode, PixelFormat, FrameSize
import gc

class CameraService:
    def __init__(self):
        # Configuração física otimizada para evitar estouro de RAM
        try:
            self.camera = Camera(
                data_pins=[11, 9, 8, 10, 12, 18, 17, 16],
                pclk_pin=13,
                vsync_pin=6,
                href_pin=7,
                sda_pin=4,
                scl_pin=5,
                xclk_pin=15,
                xclk_freq=20_000_000,
                pixel_format=PixelFormat.JPEG,
                frame_size=FrameSize.QVGA,  # Otimizado para estabilidade do barramento
                grab_mode=GrabMode.LATEST,
            )
            print("[CÂMERA] Inicializada com sucesso.")
        except Exception as e:
            self.camera = None
            print(f"[CÂMERA ERRO] Falha crítica na inicialização física: {e}")

    def bater_foto(self):
        """
        Captura um fotograma isolado de forma segura, retornando o buffer direto
        para evitar duplicação de dados e estouro de memória RAM.
        """
        if self.camera is None:
            print("[CÂMERA ERRO] Tentativa de captura com hardware offline.")
            return None
            
        quadro = None
        try:
            gc.collect()  # Força limpeza da RAM antes de alocar a imagem
            quadro = self.camera.capture()
            if quadro is None:
                raise RuntimeError("Falha na resposta física do sensor óptico (Buffer Vazio)")
            
            # Retorna o quadro diretamente em vez de bytes(quadro) para poupar RAM
            return quadro
        except Exception as e:
            print(f"[CÂMERA ERRO] Não foi possível capturar: {e}")
            return None
        # NOTA: O método free_buffer() deve ser chamado após o uso do dado (ex: após salvar)
        # Se liberarmos no finally aqui, o objeto retornado pode ser corrompido antes de gravar.

    def bater_foto_salvar(self, caminho: str = "/fotos/foto.jpeg") -> None:
        """
        Garante a captura e gravação segura no sistema de arquivos interno LittleFS.
        """
        foto = self.bater_foto()

        if foto is not None:
            try:
                # O MicroPython aceita gravar o objeto retornado pela câmera diretamente
                with open(caminho, "wb") as arquivo:
                    arquivo.write(foto)
                print(f"[SISTEMA] Foto batida e salva com sucesso em: {caminho}")
            except Exception as e:
                print(f"[ERRO LittleFS] Falha ao gravar arquivo na Flash: {e}")
            finally:
                # Libera o buffer da câmera obrigatoriamente APÓS a gravação do arquivo terminar
                if self.camera:
                    self.camera.free_buffer()
                gc.collect()
        else:
            print("[SISTEMA INTERNO] Captura abortada por falha de dados.")
