from flask import Flask, request, jsonify
import requests
import time
import sqlite3
import math

app = Flask(__name__)

DB_PATH = "localizacoes.db"

# ==============================
# DEBUG
# ==============================
@app.route("/debug", methods=["GET"])
def debug():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ultima_posicao")
        rows = cur.fetchall()
    return jsonify({
        "total_registros": len(rows),
        "dados": [dict(r) for r in rows]
    })

# ==============================
# Banco de Dados
# ==============================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ultima_posicao (
                nome TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                vel REAL,
                cog REAL,
                batt INTEGER,
                timestamp INTEGER,
                rua_cache TEXT,
                rua_cache_ts INTEGER,
                estado_movimento TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regioes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                raio_metros REAL NOT NULL
            )
        """)
        conn.commit()

def salvar_posicao(nome, data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO ultima_posicao (
                nome, lat, lon, vel, cog, batt,
                timestamp, rua_cache, rua_cache_ts, estado_movimento
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                vel=excluded.vel,
                cog=excluded.cog,
                batt=excluded.batt,
                timestamp=excluded.timestamp,
                rua_cache=excluded.rua_cache,
                rua_cache_ts=excluded.rua_cache_ts,
                estado_movimento=excluded.estado_movimento
        """, (
            nome,
            data["lat"],
            data["lon"],
            data["vel"],
            data["cog"],
            data["batt"],
            data["timestamp"],
            data.get("rua_cache"),
            data.get("rua_cache_ts"),
            data.get("estado_movimento")
        ))
        conn.commit()

def buscar_posicao(nome):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ultima_posicao WHERE nome = ?", (nome,))
        row = cur.fetchone()
        return dict(row) if row else None

def salvar_regiao(nome, lat, lon, raio_metros=40):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO regioes (nome, lat, lon, raio_metros)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                raio_metros=excluded.raio_metros
        """, (nome, lat, lon, raio_metros))
        conn.commit()

def verificar_regioes(lat, lon):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM regioes")
        regioes = cur.fetchall()
    resultado = []
    for r in regioes:
        if distancia_metros(lat, lon, r["lat"], r["lon"]) <= r["raio_metros"]:
            resultado.append(r["nome"])
    return resultado

# ==============================
# Utilidades
# ==============================
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2 +
        math.cos(phi1) * math.cos(phi2) *
        math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def formatar_tempo(segundos):
    if segundos < 120:
        return "agora"
    minutos = max(1, int(segundos / 60))
    if minutos < 60:
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"
    horas = minutos // 60
    resto = minutos % 60
    texto = f"{horas} hora{'s' if horas != 1 else ''}"
    if resto:
        texto += f" e {resto} minuto{'s' if resto != 1 else ''}"
    return texto

# ==============================
# Reverse Geocoding com POI
# ==============================
def latlon_para_rua(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1, "zoom": 18}
        headers = {"User-Agent": "OndeEsta/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        address = data.get("address", {})

        if "train_station" in address:
            return f"Estação {address['train_station']}"
        if "bus_station" in address:
            return f"Estação {address['bus_station']}"
        if "subway" in address:
            return f"Estação {address['subway']} do Metrô"

        rua = address.get("road")
        distrito = (
            address.get("city_district")
            or address.get("suburb")
            or address.get("neighbourhood")
        )
        cidade = address.get("city") or address.get("town")
        partes = [p for p in [rua, distrito, cidade] if p]
        return ", ".join(partes) if partes else None
    except:
        return None

def extrair_distrito(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1, "zoom": 18}
        headers = {"User-Agent": "OndeEsta/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        address = data.get("address", {})
        return (
            address.get("city_district")
            or address.get("suburb")
            or address.get("neighbourhood")
        )
    except:
        return None

# ==============================
# Próximo POI à frente
# ==============================
def proximo_poi(lat, lon, cog):
    for distancia_km in [0.0002, 0.0005, 0.001]:
        rad = math.radians(cog)
        lat2 = lat + distancia_km * math.cos(rad)
        lon2 = lon + distancia_km * math.sin(rad) / math.cos(math.radians(lat))

        poi = buscar_poi_prioritario(lat2, lon2, 500)
        if poi:
            distrito = extrair_distrito(lat2, lon2)
            return f"{poi} em {distrito}" if distrito else poi

    poi_sec = buscar_poi_secundario(lat, lon, 200)
    if poi_sec:
        distrito = extrair_distrito(lat, lon)
        return f"{poi_sec} em {distrito}" if distrito else poi_sec

    return "essa região"

# ==============================
# Determinar local com prioridade
# ==============================
def determinar_local_prioritario(lat, lon):
    regioes_salvas = verificar_regioes(lat, lon)
    if regioes_salvas:
        return regioes_salvas[0]

    poi = buscar_poi_prioritario(lat, lon, 1000)
    if poi:
        distrito = extrair_distrito(lat, lon)
        return f"{poi} em {distrito}" if distrito else poi

    poi2 = buscar_poi_secundario(lat, lon, 400)
    if poi2:
        distrito = extrair_distrito(lat, lon)
        return f"{poi2} em {distrito}" if distrito else poi2

    return latlon_para_rua(lat, lon) or "essa região"

# ==============================
# Init
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
