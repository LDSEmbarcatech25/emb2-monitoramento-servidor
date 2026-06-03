from camera import Camera, GrabMode, PixelFormat, FrameSize, GainCeiling

# | Nome       | Resolução   | Proporção        |
# | ---------- | ----------- | ---------------- |
# | `R96X96`   | 96 × 96     | 1:1              |
# | `QQVGA`    | 160 × 120   | 4:3              |
# | `R128x128` | 128 × 128   | 1:1              |
# | `QCIF`     | 176 × 144   | 11:9             |
# | `HQVGA`    | 240 × 176   | ~4:3             |
# | `R240X240` | 240 × 240   | 1:1              |
# | `QVGA`     | 320 × 240   | 4:3              |
# | `R320X320` | 320 × 320   | 1:1              |
# | `CIF`      | 352 × 288   | 11:9             |
# | `HVGA`     | 480 × 320   | 3:2              |
# | `VGA`      | 640 × 480   | 4:3              |
# | `SVGA`     | 800 × 600   | 4:3              |
# | `XGA`      | 1024 × 768  | 4:3              |
# | `HD`       | 1280 × 720  | 16:9             |
# | `SXGA`     | 1280 × 1024 | 5:4              |
# | `UXGA`     | 1600 × 1200 | 4:3              |
# | `FHD`      | 1920 × 1080 | 16:9             |
# | `P_HD`     | 720 × 1280  | 9:16 (portrait)  |
# | `P_3MP`    | 864 × 1536  | ~9:16 (portrait) |
# | `QXGA`     | 2048 × 1536 | 4:3              |
# | `QHD`      | 2560 × 1440 | 16:9             |
# | `WQXGA`    | 2560 × 1600 | 16:10            |
# | `P_FHD`    | 1080 × 1920 | 9:16 (portrait)  |
# | `QSXGA`    | 2560 × 2048 | 5:4              |

class CameraService:
    def __init__(self):
        self.camera = Camera(
            # data_pins=[16,17,18,12,10,8,9,11],
            data_pins=[11,9,8,10,12,18,17,16],
            pclk_pin=13,
            vsync_pin=6,
            href_pin=7,
            sda_pin=4,
            scl_pin=5,
            xclk_pin=15,
            xclk_freq=20_000_000,
            pixel_format=PixelFormat.JPEG,
            frame_size=FrameSize.QXGA,
            grab_mode=GrabMode.LATEST,
        )

    def bater_foto(self) -> bytes:
        """
        bate a foto
        """
        try:
            return bytes(self.camera.capture())
        finally:
            self.camera.free_buffer()

    def bater_foto_salvar(self,caminho:str="./foto.jpeg") -> None:
        """
        bate e salva uma foto
        """

        foto = self.bater_foto()

        with open(caminho,"wb") as arquivo:
            arquivo.write(foto)

        print(f"foto batida e salva em {caminho}")