#!/usr/bin/env python3
"""Recorta una zona del mapa mundial de Protomaps (OpenStreetMap, teselas vectoriales) a un
archivo .pmtiles chico, para usarlo offline en la app.

Lee el planeta por HTTP con pedidos de rango (no lo baja entero) y escribe un PMTiles v3 con
un solo directorio raiz. Formato: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md

    python3 extraer_mapa.py SALIDA.pmtiles MIN_LON MIN_LAT MAX_LON MAX_LAT [ZOOM_MAX]

El planeta mas nuevo sale de https://build-metadata.protomaps.dev/builds.json
"""
import gzip, hashlib, http.client, io, json, math, struct, sys, urllib.request

HOST = 'build.protomaps.com'


# ---------------------------------------------------------------- lectura remota
class Remoto:
    def __init__(self, ruta):
        self.ruta, self.con, self.pedidos = ruta, None, 0

    def leer(self, ini, n):
        for intento in range(4):
            try:
                if self.con is None:
                    self.con = http.client.HTTPSConnection(HOST, timeout=60)
                self.con.request('GET', self.ruta, headers={'Range': f'bytes={ini}-{ini + n - 1}',
                                                            'User-Agent': 'radio-juando-mapas'})
                r = self.con.getresponse()
                datos = r.read()
                if r.status != 206 or len(datos) != n:
                    raise IOError(f'HTTP {r.status}, {len(datos)} de {n} bytes')
                self.pedidos += 1
                return datos
            except Exception as e:
                self.con = None
                if intento == 3:
                    raise
                print('  reintento:', e, file=sys.stderr)


# ---------------------------------------------------------------- formato PMTiles v3
CAMPOS = ('root_off', 'root_len', 'meta_off', 'meta_len', 'leaf_off', 'leaf_len', 'data_off',
          'data_len', 'n_direcciones', 'n_entradas', 'n_contenidos')


def leer_cabecera(b):
    assert b[:7] == b'PMTiles' and b[7] == 3, 'no es PMTiles v3'
    h = dict(zip(CAMPOS, struct.unpack_from('<11Q', b, 8)))
    (h['agrupado'], h['comp_interna'], h['comp_teselas'], h['tipo'], h['zmin'], h['zmax']) = b[96:102]
    h['min_lon'], h['min_lat'], h['max_lon'], h['max_lat'] = struct.unpack_from('<4i', b, 102)
    h['zcentro'] = b[118]
    h['centro_lon'], h['centro_lat'] = struct.unpack_from('<2i', b, 119)
    return h


def escribir_cabecera(h):
    b = b'PMTiles' + bytes([3]) + struct.pack('<11Q', *(h[c] for c in CAMPOS))
    b += bytes([h['agrupado'], h['comp_interna'], h['comp_teselas'], h['tipo'], h['zmin'], h['zmax']])
    b += struct.pack('<4i', h['min_lon'], h['min_lat'], h['max_lon'], h['max_lat'])
    b += bytes([h['zcentro']]) + struct.pack('<2i', h['centro_lon'], h['centro_lat'])
    assert len(b) == 127
    return b


def descomprimir(b, comp):
    return gzip.decompress(b) if comp == 2 else b


def leer_varint(f):
    v = desp = 0
    while True:
        c = f.read(1)[0]
        v |= (c & 0x7F) << desp
        if not c & 0x80:
            return v
        desp += 7


def varint(v):
    out = bytearray()
    while True:
        c = v & 0x7F
        v >>= 7
        if v:
            out.append(c | 0x80)
        else:
            out.append(c)
            return bytes(out)


def leer_directorio(b):
    f = io.BytesIO(b)
    n = leer_varint(f)
    ids, ult = [], 0
    for _ in range(n):
        ult += leer_varint(f)
        ids.append(ult)
    corridas = [leer_varint(f) for _ in range(n)]
    largos = [leer_varint(f) for _ in range(n)]
    offs = []
    for i in range(n):
        v = leer_varint(f)
        offs.append(offs[i - 1] + largos[i - 1] if v == 0 and i > 0 else v - 1)
    return list(zip(ids, corridas, offs, largos))


def escribir_directorio(entradas):
    b = bytearray(varint(len(entradas)))
    ult = 0
    for e in entradas:
        b += varint(e[0] - ult)
        ult = e[0]
    for e in entradas:
        b += varint(e[1])
    for e in entradas:
        b += varint(e[3])
    for i, e in enumerate(entradas):
        contiguo = i > 0 and e[2] == entradas[i - 1][2] + entradas[i - 1][3]
        b += varint(0 if contiguo else e[2] + 1)
    return bytes(b)


def zxy_a_id(z, x, y):
    """Numero de tesela PMTiles: teselas de los zoom anteriores + posicion en la curva de Hilbert."""
    acc = ((1 << (2 * z)) - 1) // 3
    n = 1 << z
    s = n >> 1
    d = 0
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = n - 1 - x, n - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def lon_a_x(lon, z):
    return int((lon + 180) / 360 * (1 << z))


def lat_a_y(lat, z):
    r = math.radians(lat)
    return int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * (1 << z))


# ---------------------------------------------------------------- principal
def main():
    salida = sys.argv[1]
    min_lon, min_lat, max_lon, max_lat = map(float, sys.argv[2:6])
    zmax_pedido = int(sys.argv[6]) if len(sys.argv) > 6 else 15

    pedido = urllib.request.Request('https://build-metadata.protomaps.dev/builds.json', headers={'User-Agent': 'radio-juando-mapas'})
    builds = json.load(urllib.request.urlopen(pedido))
    clave = sorted(b['key'] for b in builds)[-1]
    print('planeta:', clave)
    r = Remoto('/' + clave)

    h = leer_cabecera(r.leer(0, 127))
    comp = h['comp_interna']
    raiz = leer_directorio(descomprimir(r.leer(h['root_off'], h['root_len']), comp))
    meta = json.loads(descomprimir(r.leer(h['meta_off'], h['meta_len']), comp))
    zmax = min(zmax_pedido, h['zmax'])
    hojas = {}

    def buscar(dir_, tid):
        lo, hi = 0, len(dir_) - 1
        while lo <= hi:                   # ultima entrada con id <= tid
            m = (lo + hi) // 2
            if dir_[m][0] <= tid:
                lo = m + 1
            else:
                hi = m - 1
        return dir_[hi] if hi >= 0 else None

    def ubicar(tid):
        dir_ = raiz
        for _ in range(4):
            e = buscar(dir_, tid)
            if e is None:
                return None
            if e[1] > 0:                  # tesela (o corrida de teselas iguales)
                return (e[2], e[3]) if tid < e[0] + e[1] else None
            clave_hoja = (e[2], e[3])     # directorio hoja
            if clave_hoja not in hojas:
                hojas[clave_hoja] = leer_directorio(descomprimir(r.leer(h['leaf_off'] + e[2], e[3]), comp))
            dir_ = hojas[clave_hoja]
        return None

    # que teselas hacen falta
    pedidas = []
    for z in range(h['zmin'], zmax + 1):
        x0, x1 = lon_a_x(min_lon, z), lon_a_x(max_lon, z)
        y0, y1 = lat_a_y(max_lat, z), lat_a_y(min_lat, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                pedidas.append((zxy_a_id(z, x, y), z))
    pedidas.sort()
    print(f'{len(pedidas)} teselas de z{h["zmin"]} a z{zmax}')

    # bajar (las que estan seguidas en el planeta se piden juntas)
    ubic = [(tid, ubicar(tid)) for tid, _ in pedidas]
    ubic = [(tid, u) for tid, u in ubic if u]
    por_off = sorted(set(u for _, u in ubic))
    contenido = {}
    i = 0
    while i < len(por_off):
        ini, fin, j = por_off[i][0], por_off[i][0] + por_off[i][1], i + 1
        while j < len(por_off) and por_off[j][0] <= fin + 4096 and por_off[j][0] + por_off[j][1] - ini < 4_000_000:
            fin = max(fin, por_off[j][0] + por_off[j][1])
            j += 1
        bloque = r.leer(h['data_off'] + ini, fin - ini)
        for off, n in por_off[i:j]:
            contenido[(off, n)] = bloque[off - ini: off - ini + n]
        i = j
        print(f'\r  {len(contenido)}/{len(por_off)} contenidos', end='', file=sys.stderr)
    print(file=sys.stderr)

    # escribir: datos en orden de id, contenidos repetidos (agua, campo) una sola vez
    datos = bytearray()
    ya = {}
    entradas = []
    for tid, u in ubic:
        b = contenido[u]
        hsh = hashlib.sha1(b).digest()
        if hsh not in ya:
            ya[hsh] = (len(datos), len(b))
            datos += b
        off, n = ya[hsh]
        if entradas and entradas[-1][0] + entradas[-1][1] == tid and entradas[-1][2] == off:
            entradas[-1] = (entradas[-1][0], entradas[-1][1] + 1, off, n)
        else:
            entradas.append((tid, 1, off, n))

    raiz_b = gzip.compress(escribir_directorio(entradas), mtime=0)
    meta['radio_juando'] = f'recorte de {clave}, bbox {min_lon},{min_lat},{max_lon},{max_lat}, z{h["zmin"]}-{zmax}'
    meta_b = gzip.compress(json.dumps(meta).encode(), mtime=0)
    assert 127 + len(raiz_b) <= 16384, 'el directorio no entra en la raiz: achicar la zona o el zoom'

    nh = dict(h)
    nh.update(comp_interna=2, agrupado=1, zmax=zmax,
              root_off=127, root_len=len(raiz_b),
              meta_off=127 + len(raiz_b), meta_len=len(meta_b),
              leaf_off=127 + len(raiz_b) + len(meta_b), leaf_len=0,
              n_direcciones=len(ubic), n_entradas=len(entradas), n_contenidos=len(ya),
              min_lon=round(min_lon * 1e7), min_lat=round(min_lat * 1e7),
              max_lon=round(max_lon * 1e7), max_lat=round(max_lat * 1e7),
              zcentro=min(13, zmax),
              centro_lon=round((min_lon + max_lon) / 2 * 1e7), centro_lat=round((min_lat + max_lat) / 2 * 1e7))
    nh['data_off'] = nh['leaf_off']
    nh['data_len'] = len(datos)
    with open(salida, 'wb') as f:
        f.write(escribir_cabecera(nh) + raiz_b + meta_b + datos)
    print(f'{salida}: {len(ubic)} teselas, {len(ya)} distintas, {(127 + len(raiz_b) + len(meta_b) + len(datos)) / 1e6:.1f} MB, '
          f'{r.pedidos} pedidos HTTP')


if __name__ == '__main__':
    main()
