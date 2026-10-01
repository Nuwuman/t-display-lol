#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini backend para el T-Display de LoL. 100% libreria estandar (no hace falta pip).

Sirve en tu red local:
  GET /champions               -> estructura lineas->campeones (roster)
  GET /build?champ=kled        -> build JSON (items nombre+id, patch, nota)
  GET /icon/<itemid>.bin       -> icono del item en RGB565 40x40 raw (3200 B)

Uso:   python3 backend.py   (escucha en 0.0.0.0:8000)
Datos de campeones/builds -> builds.json (mismo folder).
Iconos y nombres de items <- Data Dragon de Riot, cacheados en ./icocache.
"""
import json, os, sys, struct, zlib, urllib.request, random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
CDN = "https://ddragon.leagueoflegends.com/cdn/16.19.1"
ICON_W = ICON_H = 40  # px; RGB565 -> 3200 bytes/icono
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "icocache")

# Pool de items reales (icono verificado en CDN) para el modo RANDOM.
RANDOM_ITEMS = [6676, 3031, 3046, 3036, 3072, 3033, 6673, 3026, 3035, 6695,
                6697, 3032, 3139, 3156, 6655, 4645, 4646, 3089, 3135, 3157,
                3102, 3041, 3152, 6657, 3003, 3748, 3071, 3053, 3181, 3143,
                2501, 3110, 3302, 2523, 2522]
RANDOM_BOOTS = [3006, 3020, 3047, 3158, 3009, 3111]


# ---------- PNG (solo stdlib: zlib) ----------
def png_decode(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, W, H, ct, rawidat = 8, None, None, None, b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        d = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            W, H, _, ct = struct.unpack(">IIBB", d[:10])
        elif typ == b"IDAT":
            rawidat += d
        elif typ == b"IEND":
            break
    raw = zlib.decompress(rawidat)
    nch = 3 if ct == 2 else 4  # RGB o RGBA
    stride = W * nch
    out = bytearray(H * stride)
    prev = bytearray(stride)

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    for y in range(H):
        off = y * (stride + 1)
        f = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        row = y * stride
        for x in range(stride):
            # 'a' (izq) debe ser el pixel YA reconstruido de esta fila (out),
            # no el byte crudo 'line': los filtros Sub/Average/Paeth lo exigen.
            a = out[row + x - nch] if x >= nch else 0
            b = prev[x]
            c = prev[x - nch] if x >= nch else 0
            v = line[x]
            if f == 1: v = (v + a) & 255
            elif f == 2: v = (v + b) & 255
            elif f == 3: v = (v + ((a + b) >> 1)) & 255
            elif f == 4: v = (v + paeth(a, b, c)) & 255
            out[row + x] = v
        prev = out[row:row + stride]
    return W, H, out


def to_rgb565_bin(img, sw, sh, dw, dh):
    """redimensiona (nearest) y emite RGB565 big-endian (byte alto primero)."""
    out = bytearray(dw * dh * 2)
    k = 0
    for dy in range(dh):
        sy = dy * sh // dh
        for dx in range(dw):
            sx = dx * sw // dw
            i = (sy * sw + sx) * 3
            r, g, b = img[i], img[i + 1], img[i + 2]
            # Panel BGR: lee bits15-11 como AZUL y bit4-0 como ROJO (rojo->azul).
            # Para compensar, emitimos B en el campo alto y R en el bajo.
            c = ((b >> 3) << 11) | ((g >> 2) << 5) | (r >> 3)
            out[k] = c >> 8      # big-endian: byte ALTO primero
            out[k + 1] = c & 0xFF
            k += 2
    return bytes(out)


# ---------- datos ----------
def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_item_db():
    path = os.path.join(CACHE, "item.json")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        open(path, "wb").write(http_get(f"{CDN}/data/en_US/item.json"))
    return json.load(open(path))["data"]


def item_name(db, iid):
    it = db.get(str(iid))
    return it["name"] if it else f"Item {iid}"


def icon_rgb565(db, iid):
    cpath = os.path.join(CACHE, f"{iid}.bin")
    if os.path.exists(cpath):
        return open(cpath, "rb").read()
    png = http_get(f"{CDN}/img/item/{iid}.png")
    w, h, rgb = png_decode(png)
    blob = to_rgb565_bin(rgb, w, h, ICON_W, ICON_H)
    open(cpath, "wb").write(blob)
    return blob


def load_builds():
    return json.load(open(os.path.join(HERE, "builds.json")))


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    builds = items = None

    def log_message(self, *a): pass

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        if H.builds is None:
            H.builds = load_builds()
            H.items = load_item_db()
        p = urlparse(self.path)
        if p.path == "/champions":
            self._send(200, json.dumps(H.builds["lanes"]).encode(), "application/json")
        elif p.path == "/build":
            champ = parse_qs(p.query).get("champ", [""])[0].lower()
            self._send(200, json.dumps(self._find_build(champ)).encode(), "application/json")
        elif p.path.startswith("/icon/"):
            iid = p.path[len("/icon/"):].rsplit(".", 1)[0]
            if iid.isdigit():
                try:
                    self._send(200, icon_rgb565(H.items, iid), "application/octet-stream",
                               {"Cache-Control": "max-age=86400"})
                    return
                except Exception as e:
                    self._send(502, str(e).encode(), "text/plain")
                    return
            self._send(404, b"not found", "text/plain")
        elif p.path == "/random":
            picks = random.sample(RANDOM_ITEMS, 5)
            boots = random.choice(RANDOM_BOOTS)
            item_ids = picks + [boots]
            build = {
                "champion": "RANDOM",
                "role": "-",
                "patch": H.builds["patch"],
                "items": [{"name": item_name(H.items, i), "id": str(i)}
                          for i in item_ids],
                "note": "",
            }
            self._send(200, json.dumps(build).encode(), "application/json")
        elif p.path == "/main.py":
            try:
                with open(os.path.join(HERE, "main.py"), "rb") as f:
                    self._send(200, f.read(), "text/plain",
                               {"Content-Disposition": 'attachment; filename="main.py"'})
                return
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
                return
        elif p.path == "/test_color.py":
            try:
                with open(os.path.join(HERE, "firmware", "test_color.py"), "rb") as f:
                    self._send(200, f.read(), "text/plain",
                               {"Content-Disposition": 'attachment; filename="test_color.py"'})
                return
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
                return
        elif p.path == "/test_frame.py":
            try:
                with open(os.path.join(HERE, "firmware", "test_frame.py"), "rb") as f:
                    self._send(200, f.read(), "text/plain",
                               {"Content-Disposition": 'attachment; filename="test_frame.py"'})
                return
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
                return
        elif p.path == "/test_blit.py":
            try:
                with open(os.path.join(HERE, "firmware", "test_blit.py"), "rb") as f:
                    self._send(200, f.read(), "text/plain",
                               {"Content-Disposition": 'attachment; filename="test_blit.py"'})
                return
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
                return
        elif p.path == "/":
            self._send(200, b"LoL T-Display backend OK", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def _find_build(self, champ):
        if champ in ("", "none"):
            return {"error": "faltan champ"}
        for lane in H.builds["lanes"]:
            for ch in lane["champions"]:
                if ch["name"].lower() == champ:
                    return {
                        "champion": ch["name"],
                        "role": lane["lane"],
                        "patch": H.builds["patch"],
                        "items": [{"name": item_name(H.items, i), "id": str(i)}
                                  for i in ch["build"]["items"]],
                        "note": ch["build"].get("note", ""),
                    }
        return {"error": f"'{champ}' no esta en builds.json"}


if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    print("T-Display LoL backend -> http://0.0.0.0:%d  (iconos %dx%d RGB565)" % (PORT, ICON_W, ICON_H))
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
