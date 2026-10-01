# T-Display LoL Builder

Pantalla del LilyGO T-Display (ESP32, 1.14" ST7789) que muestra la build de LoL
del campeon que eliges, con iconos. Menos de 1 segundo tras pulsar.

```
ESP32 (T-Display)  --WiFi-->  backend.py (tu PC)  --Riot Data Dragon-->  datos reales
     pantalla                          ^ builds.json (tu lista)
```

## Archivos
- `backend.py`   -> servidor local puro (sin instalar nada, solo Python 3)
- `builds.json`  -> la lista LINEAS->CAMPIONES->builds que tu editas
- `main.py`      -> firmware del ESP32 (driver ST7789 INLINE + menu + red + iconos)
- `firmware/`    -> copia de referencia de `main.py` (misma version que sirve /main.py)

---

## 1) Backend (en tu PC / Proxmox, en la MISMA wifi que el ESP32)

1. Entra a la carpeta y lanza:
   ```
   python3 backend.py
   ```
2. Debe decir algo como `T-Display LoL backend -> http://0.0.0.0:8000`.
   Deja esa terminal abierta (o ponlo como servicio/systemd si quieres que corra solo).
3. Averigua la IP de ese equipo para meterla en el firmware:
   - Windows: `ipconfig` -> IP de IPv4 (ej. 192.168.1.20)
   - Linux:   `hostname -I`   (ej. 192.168.1.20)

Prueba rapida en el navegador de tu PC:
- `http://localhost:8000/champions`  -> lista de lineas/campeones
- `http://localhost:8000/build?champ=neeko` -> build de Neeko con nombres reales

### Editar los campeones / builds
Abre `builds.json`. Un ejemplo de entrada:

```json
{ "name": "Ryze", "build": { "items": [773027, 773040, 773089, 773135, 773157], "note": "RoA + Seraph's" } }
```

- `items` son los IDs de Riot; el backend muestra el NOMBRE real e icono de cada uno.
  No hace falta saber los nombres de memoria: pon el ID y el aparato lo dibuja.
- Para anadir un campeon: ponlo bajo `champions` de su linea. Deja `"champions": []`
  en las lineas que no uses para no mostrar una pantalla vacia.

> NOTA TRANSPARENTE: builds.json empieza con datos de ejemplo. El "meta real con
> winrate" (U.GG/Mobalytics) esta detras de proteccion anti-bot y no hay API publica;
> por eso la build se edita a mano (o la actualizas tu). El pipeline funciona igual:
> tu pones los IDs y el aparato dibuja nombres + iconos + tu nota.

---

## 2) Flashear el ESP32 con MicroPython

1. Baja el firmware ESP32 (generic) desde:
   https://micropython.org/download/ESP32_GENERIC/
   (archivo `.bin`; con ESP-IDF viene del tipo `ESP32_GENERIC-*-v1.23.0.bin`).

2. Instala esptool (necesitas Python en tu PC):
   ```
   pip install esptool
   ```

3. Conecta el T-Display por USB. Busca el puerto:
   - Windows: Administrador de dispositivos -> Puertos (COM y LPT) -> COMx
   - Linux:   normalmente `/dev/ttyUSB0`

4. Borra y graba (cambia COMx por tu puerto):
   ```
   esptool.py --chip esp32 --port COMx erase_flash
   esptool.py --chip esp32 --port COMx --baud 460800 write_flash -z 0x1000 ESP32_GENERIC-XXX.bin
   ```
   Si entra en modo bootloader solo: mantén pulsado el boton RST (o el BOOT/GPIO0)
   mientras conectas el USB; el T-Display normalmente auto-entra via CH9102.

5. Reinicia (boton RST). Si abres Thonny (Run -> Select interpreter -> MicroPython
   ESP32) deberia ver el `>>>` de MicroPython.

---

## 3) Subir el firmware
El firmware ya NO depende de `st7789.py`: el driver ST7789 esta inline dentro de
`main.py`. Sube solo `main.py` a la placa.

Con Thonny (recomendado): en la pestana "Este equipo" arrastra `main.py` a la
placa (en "MicroPython device"). O para evitar los errores de pegado en Thonny,
descarga el archivo BYTE-A-BYTE desde el propio backend y, en Thonny, File ->
Open del lugar que lo guardaste -> Save As en la placa:
```
http://BACKEND:8000/main.py
```
Verificado que este /main.py roundtrip-ea identico (mismo sha256) al archivo local.

Antes: edita en `main.py` las lineas de arriba:
```python
SSID = "TU_WIFI"
WIFI_PASS = "TU_PASSWORD"
BACKEND = "192.168.1.100"   # la IP del PC/Proxmox con backend.py
PORT = 8000
```

Reinicia el T-Display (RST). Veras "Conectando..." y luego el menu de lineas.

---

## 4) Uso
- BOTON 1 (GPIO35): moverte a la siguiente opcion.
- BOTON 2 (GPIO0):  entrar / confirmar (auto-import: el campeon se recuerda tras apagar).

Flujo: LINEA (TOP/JUNGLE/MID/ADC/SUP) -> CAMPION de esa linea -> build con iconos.
Cualquier pulso te devuelve a las lineas.

---

## Si la imagen sale al reves / vacia / mal orientada
En `main.py` (driver inline):
- Orientacion: cambia `data(0x08)` de la linea `cmd(0x36)` (0x00 normal / 0x60 girado
  180 / 0x30 o 0xA0 girado 90).
- Si la imagen sale en una esquina/cortada: ajusta los `+52`/`+40` dentro de
  `window()` (offset de panel de clones).
- Si los colores salen raros (rojo<->azul): el blob se sirve little-endian; si la
  rojo/verde/azul salen cambiados, toca el packer en `backend.py:to_rgb565_bin`
  (no el byte order). Esto es lo unico que puede requerir ajuste fisico en tu placa.

---

## Nota de honestidad sobre este proyecto
Backend probado y verificado aqui (JSON + iconos RGB565 reales). El firmware del
ESP32 esta escrito contra el pinout documentado del T-Display, pero no puedo
flashearlo/probarlo por ti: la primera vez puede necesitar el ajuste de orientacion
de arriba. El "meta real" no es automatizable gratis (anti-bot en U.GG/Mobalytics);
por eso la lista se edita a mano en builds.json.
