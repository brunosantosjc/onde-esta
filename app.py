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
    for r in regioes:
        if distancia_metros(lat, lon, r["lat"], r["lon"]) <= r["raio_metros"]:
            return r["nome"]
    return None

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
    minutos = max(1, int(segundos / 60))
    if minutos < 60:
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"
    horas = minutos // 60
    resto = minutos % 60
    texto = f"{horas} hora{'s' if horas != 1 else ''}"
    if resto:
        texto += f" e {resto} minuto{'s' if resto != 1 else ''}"
    return texto

def calcular_bearing(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def angulo_diferenca(a, b):
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)

# ==============================
# POI à frente (Overpass)
# ==============================
def buscar_poi_a_frente(lat, lon, cog, raio=500):
    query = f"""
    [out:json];
    (
      node(around:{raio},{lat},{lon})["railway"="station"];
      node(around:{raio},{lat},{lon})["amenity"="bus_station"];
      node(around:{raio},{lat},{lon})["amenity"="shopping_mall"];
      node(around:{raio},{lat},{lon})["leisure"="park"];
    );
    out center;
    """
    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query,
            timeout=15,
            headers={"User-Agent": "OndeEsta/1.0"}
        )
        data = r.json()
        melhor = None
        menor_dist = 999999

        for el in data.get("elements", []):
            plat = el.get("lat")
            plon = el.get("lon")
            nome = el.get("tags", {}).get("name")
            if not plat or not plon or not nome:
                continue

            bearing_poi = calcular_bearing(lat, lon, plat, plon)
            if angulo_diferenca(cog, bearing_poi) <= 45:
                dist = distancia_metros(lat, lon, plat, plon)
                if dist < menor_dist:
                    menor_dist = dist
                    melhor = nome

        return melhor
    except:
        return None

# ==============================
# /where
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    pos = buscar_posicao(nome.lower())
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    lat = pos["lat"]
    lon = pos["lon"]

    regiao = verificar_regioes(lat, lon)
    local = regiao or pos.get("rua_cache") or "esse local"

    estado = pos["estado_movimento"]
    verbo = "está parado" if estado == "parado" else "está passando"

    texto = f"{nome.capitalize()} {verbo} próximo a {local}. Você quer mais detalhes?"
    return jsonify({"resposta": texto})

# ==============================
# /details
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    pos = buscar_posicao(nome.lower())
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    agora = int(time.time())
    delta = agora - pos["timestamp"]
    tempo = formatar_tempo(delta)

    lat = pos["lat"]
    lon = pos["lon"]
    estado = pos["estado_movimento"]

    regiao = verificar_regioes(lat, lon)
    local = regiao or pos.get("rua_cache") or "esse local"

    if estado == "parado":
        texto = f"Essa pessoa está parada nesse local há {tempo}, bateria {pos['batt']}%."
        precisa_salvar = regiao is None
        if precisa_salvar:
            texto += " Você quer salvar um nome para essa região?"
    else:
        vel_kmh = round(pos["vel"] * 3.6)
        ritmo = "rápido" if vel_kmh > 7 else "devagar"
        quando = "agora" if delta < 120 else f"há {tempo}"
        verbo = "está passando" if delta < 120 else "passou próximo"

        poi = buscar_poi_a_frente(lat, lon, pos["cog"])
        direcao_poi = f" em direção à {poi}" if poi else ""

        texto = (
            f"Essa pessoa {verbo} {ritmo} por esse local {quando}"
            f"{direcao_poi}, bateria {pos['batt']}%."
        )
        precisa_salvar = False

    return jsonify({
        "detalhes": texto,
        "precisa_salvar_regiao": precisa_salvar,
        "lat": lat,
        "lon": lon
    })

# ==============================
# Init
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
