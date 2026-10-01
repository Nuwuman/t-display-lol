# T-Display LoL - firmware canónico (driver ST7789 inline, un icono grande).
# Version activa del T-Display (ESP32, 135x240). SIN import st7789.py: el driver
# esta dentro. Muestra la build del campeon elegido como iconos 96x96 grandes,
# uno por pantalla; B_NEXT recorre los items, B_ENTER vuelve al menu.
#
# CAMBIA AQUI (SSID/wifi/backend):
SSID = "TU_WIFI"
WIFI_PASS = "TU_PASSWORD"
BACKEND = "192.168.1.100"   # IP de tu PC/backend
PORT = 8000

# Ajuste de panel (medido con test_frame.py): tu placa es el clon que necesita
# desplazar lo dibujado 52 px en X y 40 px en Y para centrarlo en el cristal.
OFFSET_X = 52
OFFSET_Y = 40

import network, socket, time, json, framebuf, gc
from machine import Pin, SPI

# ---- driver ST7789 inline ----
CS = Pin(5, Pin.OUT)
DC = Pin(16, Pin.OUT)
RST = Pin(23, Pin.OUT)
BL = Pin(4, Pin.OUT)
SPI = SPI(1, baudrate=20000000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))


def cmd(c):
    CS(0); DC(0); SPI.write(bytearray([c])); DC(1); CS(1)


def data(d):
    if isinstance(d, int):
        buf = bytearray([d])
    elif isinstance(d, (bytes, bytearray)):
        buf = d
    else:
        buf = bytearray(d)
    CS(0); DC(1)
    SPI.write(buf)
    CS(1)


def window(x0, y0, x1, y1):
    # Si el offset se pasa del area real (135x240), el controlador DOBLA las
    # columnas/filas sobrantes sobre el otro lado -> ruido sobre una imagen
    # reconocible. Por eso va por defecto en 0.
    cmd(0x2A); data([(x0 + OFFSET_X) >> 8, (x0 + OFFSET_X) & 0xFF,
                     (x1 + OFFSET_X) >> 8, (x1 + OFFSET_X) & 0xFF])
    cmd(0x2B); data([(y0 + OFFSET_Y) >> 8, (y0 + OFFSET_Y) & 0xFF,
                     (y1 + OFFSET_Y) >> 8, (y1 + OFFSET_Y) & 0xFF])
    cmd(0x2C)


RST(0); time.sleep_ms(50); RST(1); time.sleep_ms(120)
cmd(0x01); time.sleep_ms(120)
cmd(0x11); time.sleep_ms(120)
cmd(0x3A); data(0x55)
cmd(0x36); data(0x08)
cmd(0x21)
cmd(0x13); time.sleep_ms(10)
cmd(0x29); time.sleep_ms(120)
BL(1)

# ---- framebuf ----
W, H = 135, 240
WHITE = 0xFFFF
fbuf = bytearray(W * H * 2)
fb = framebuf.FrameBuffer(fbuf, W, H, framebuf.RGB565)
icon_cache = {}
ICON = 40  # debe coincidir con ICON_W/ICON_H del backend (40 = 3200 B/icono)


def push():
    window(0, 0, 134, 239)
    CS(0); DC(1); SPI.write(fbuf); CS(1)


def show(msg):
    fb.fill(0)
    y = 10
    for line in msg.split("\n"):
        if line:
            fb.text(line[:16], 4, y, WHITE)
            y += 16
    push()


# ---- botones (T-Display) ----
B_NEXT = Pin(35, Pin.IN)
B_ENTER = Pin(0, Pin.IN, Pin.PULL_UP)

# ---- red ----
def connect_wifi():
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        w.connect(SSID, WIFI_PASS)
        for _ in range(40):
            if w.isconnected():
                break
            time.sleep(0.25)
    return w.isconnected()


def http_fetch(path, is_json=True):
    s = socket.socket()
    s.settimeout(6)
    s.connect(socket.getaddrinfo(BACKEND, PORT)[0][4])
    s.send(b"GET " + path.encode() + b" HTTP/1.0\r\nHost: " + BACKEND.encode() + b"\r\nUser-Agent: pico\r\nConnection: close\r\n\r\n")
    data_b = b""
    while True:
        chunk = s.recv(512)
        if not chunk:
            break
        data_b += chunk
    s.close()
    body = data_b.split(b"\r\n\r\n", 1)[1]
    if is_json:
        return json.loads(body.decode("utf-8"))
    return body


def wait_press(b):
    if b.value() == 0:
        time.sleep_ms(40)
        if b.value() == 0:
            while b.value() == 0:
                time.sleep_ms(10)
            return True
    return False


def wait_release(b, ms=200):
    """Espera a que el boton suelte y luego un margen quieto (anti-rebote)."""
    while b.value() == 0:
        time.sleep_ms(10)
    time.sleep_ms(ms)


def resolve_icons(items):
    # RAM: se ve UNA build a la vez, asi que siempre se limpia lo que haya de
    # otro campeon antes de bajar esta. Evita que la cache crezca y congele el
    # ESP32 al entrar a campeones seguidos (~6 iconos x 3200 B ~ 19 KB max).
    if icon_cache:
        icon_cache.clear()
        gc.collect()
    for it in items:
        iid = it["id"]
        if iid not in icon_cache:
            b = None
            for _ in range(2):          # reintento si el primer fetch fallo
                try:
                    b = bytearray(http_fetch("/icon/%s.bin" % iid, False))
                    if len(b) == ICON * ICON * 2:
                        break
                    b = None
                except Exception:
                    b = None
                gc.collect()
            icon_cache[iid] = b          # None -> se dibuja solo el nombre
        gc.collect()


def draw_icon(iid, x, y):
    b = icon_cache.get(iid)
    if b and len(b) >= ICON * ICON * 2:
        ib = framebuf.FrameBuffer(b, ICON, ICON, framebuf.RGB565)
        fb.blit(ib, x, y)


def draw_build(build, items):
    fb.fill(0)
    fb.text((build["champion"] + "  " + build["patch"])[:16], 4, 2, WHITE)
    # grid de iconos 40x40, 3 por fila
    colx = [4, 48, 92]
    for i, it in enumerate(items[:6]):
        draw_icon(it["id"], colx[i % 3], 18 + (i // 3) * 42)
    # nombres
    y = 18 + 42 * 2 + 4
    for it in items[:6]:
        fb.text(it["name"][:16], 4, y, WHITE)
        y += 12
        if y > H - 16:
            break
    push()


def menu(rows):
    cur = 0
    while True:
        fb.fill(0)
        for i, r in enumerate(rows):
            fb.text(("> " if i == cur else "  ") + r[:11], 4, 16 + i * 30, WHITE)
        push()
        if wait_press(B_ENTER):
            return cur
        if wait_press(B_NEXT):
            cur = (cur + 1) % len(rows)
        time.sleep_ms(10)


def confirm(champ):
    try:
        if champ == "random":
            build = http_fetch("/random")          # 5 items + botas al azar
        else:
            build = http_fetch("/build?champ=%s" % champ)
        if "error" in build:
            show("SIN DATOS:\n" + build["error"])
            time.sleep(2)
            return
        items = build["items"]
        resolve_icons(items)
        draw_build(build, items)
    except Exception as e:
        show("ERROR RED:\n" + str(e)[:20])
        time.sleep(2)
    # quedarse en la build hasta que el usuario pulse B_ENTER (la confirmacion
    # del campeon podria estar aun soltandose: espera quieta antes de armar).
    wait_release(B_ENTER)
    while not wait_press(B_ENTER):
        time.sleep_ms(10)


# ---- arranque ----
show("Conectando...")
if not connect_wifi():
    show("SIN WIFI\nrevisa SSID/IP")
    while True:
        time.sleep(1)

ip = network.WLAN(network.STA_IF).ifconfig()[0]
show("Conectado\nIP: %s\nCargando..." % ip)

try:
    lanes = http_fetch("/champions")
except Exception as e:
    show("BACKEND no\nresponde\n%s\n(err=%s)" % (BACKEND, str(e)[:8]))
    while True:
        time.sleep(1)

lineas = [l for l in lanes if l["champions"]]
if len(lineas) == 1:
    li = 0
else:
    li = menu([l["lane"] for l in lineas])

while True:
    lane = lineas[li]
    rows = ["RANDOM"] + [c["name"] for c in lane["champions"]]
    if len(rows) == 1:
        show("Linea %s sin\ncampeones" % lane["lane"])
        time.sleep(1.5)
        li = menu([l["lane"] for l in lineas])
        continue
    ci = menu(rows)
    champ = "random" if ci == 0 else lane["champions"][ci - 1]["name"]
    confirm(champ)
    li = menu([l["lane"] for l in lineas])