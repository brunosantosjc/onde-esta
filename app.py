from flask import Flask, request, jsonify
import requests
import time
import psycopg2
import psycopg2.extras
import math
import os

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ==============================
# Banco de Dados
# ==============================
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ultima_posicao (
                    nome TEXT PRIMARY KEY,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    vel DOUBLE PRECISION,
                    cog DOUBLE PRECISION,
                    batt INTEGER,
                    timestamp INTEGER,
                    rua_cache TEXT,
                    rua_cache_ts INTEGER,
                    poi_cache TEXT,
                    poi_cache_ts INTEGER,
                    poi_cache_cog DOUBLE PRECISION,
                    estado_movimento TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS regioes (
                    id SERIAL PRIMARY KEY,
                    nome TEXT UNIQUE,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    raio_metros DOUBLE PRECISION
                );
            """)
        conn.commit()

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
# Reverse Geocoding
# ==============================
def latlon_para_rua(lat, lon):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 18
            },
            headers={"User-Agent": "OndeEsta/1.0"},
            timeout=10
        )
        return r.json().get("display_name")
    except:
        return None

# ==============================
# POI à frente
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
    out;
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
        menor_dist = 1e9

        for el in data.get("elements", []):
            plat = el.get("lat")
            plon = el.get("lon")
            nome = el.get("tags", {}).get("name")
            if not plat or not plon or not nome:
                continue

            bearing = calcular_bearing(lat, lon, plat, plon)
            if angulo_diferenca(cog, bearing) <= 45:
                dist = distancia_metros(lat, lon, plat, plon)
                if dist < menor_dist:
                    menor_dist = dist
                    melhor = nome

        return melhor
    except:
        return None

# ==============================
# Regiões
# ==============================
def verificar_regioes(lat, lon):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM regioes")
            for r in cur.fetchall():
                if distancia_metros(lat, lon, r["lat"], r["lon"]) <= r["raio_metros"]:
                    return r["nome"]
    return None

# ==============================
# Persistência
# ==============================
def salvar_posicao(nome, data):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ultima_posicao VALUES (
                    %(nome)s,%(lat)s,%(lon)s,%(vel)s,%(cog)s,%(batt)s,
                    %(timestamp)s,%(rua_cache)s,%(rua_cache_ts)s,
                    %(poi_cache)s,%(poi_cache_ts)s,%(poi_cache_cog)s,
                    %(estado_movimento)s
                )
                ON CONFLICT (nome) DO UPDATE SET
                    lat=EXCLUDED.lat,
                    lon=EXCLUDED.lon,
                    vel=EXCLUDED.vel,
                    cog=EXCLUDED.cog,
                    batt=EXCLUDED.batt,
                    timestamp=EXCLUDED.timestamp,
                    rua_cache=EXCLUDED.rua_cache,
                    rua_cache_ts=EXCLUDED.rua_cache_ts,
                    poi_cache=EXCLUDED.poi_cache,
                    poi_cache_ts=EXCLUDED.poi_cache_ts,
                    poi_cache_cog=EXCLUDED.poi_cache_cog,
                    estado_movimento=EXCLUDED.estado_movimento
            """, {
                **data,
                "nome": nome.lower()
            })
        conn.commit()

def buscar_posicao(nome):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM ultima_posicao WHERE nome=%s", (nome.lower(),))
            r = cur.fetchone()
            return dict(r) if r else None

# ==============================
# UPDATE
# ==============================
@app.route("/update", methods=["POST"])
def update():
    data = request.json
    if not data or "nome" not in data:
        return jsonify({"erro": "Dados inválidos"}), 400

    agora = int(time.time())
    data["timestamp"] = data.get("timestamp", agora)

    pos_ant = buscar_posicao(data["nome"])

    data["estado_movimento"] = "andando" if data.get("vel", 0) > 0.5 else "parado"

    # Rua
    precisa_rua = (
        not pos_ant or
        not pos_ant.get("rua_cache") or
        agora - (pos_ant.get("rua_cache_ts") or 0) > 600 or
        distancia_metros(pos_ant["lat"], pos_ant["lon"], data["lat"], data["lon"]) > 50
    )

    if precisa_rua:
        data["rua_cache"] = latlon_para_rua(data["lat"], data["lon"])
        data["rua_cache_ts"] = agora
    else:
        data["rua_cache"] = pos_ant["rua_cache"]
        data["rua_cache_ts"] = pos_ant["rua_cache_ts"]

    # POI
    precisa_poi = (
        data["estado_movimento"] == "andando" and (
            not pos_ant or
            not pos_ant.get("poi_cache") or
            agora - (pos_ant.get("poi_cache_ts") or 0) > 300 or
            angulo_diferenca(pos_ant.get("poi_cache_cog", 0), data.get("cog", 0)) > 30 or
            distancia_metros(pos_ant["lat"], pos_ant["lon"], data["lat"], data["lon"]) > 100
        )
    )

    if precisa_poi:
        data["poi_cache"] = buscar_poi_a_frente(data["lat"], data["lon"], data.get("cog", 0))
        data["poi_cache_ts"] = agora
        data["poi_cache_cog"] = data.get("cog", 0)
    else:
        data["poi_cache"] = pos_ant.get("poi_cache")
        data["poi_cache_ts"] = pos_ant.get("poi_cache_ts")
        data["poi_cache_cog"] = pos_ant.get("poi_cache_cog")

    salvar_posicao(data["nome"], data)
    return jsonify({"status": "ok"})

# ==============================
# WHERE
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    pos = buscar_posicao(nome)
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    local = verificar_regioes(pos["lat"], pos["lon"]) or pos["rua_cache"] or "esse local"
    verbo = "está parado" if pos["estado_movimento"] == "parado" else "está passando"

    return jsonify({
        "resposta": f"{nome.capitalize()} {verbo} próximo a {local}. Você quer mais detalhes?"
    })

# ==============================
# DETAILS
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    pos = buscar_posicao(nome)
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    if pos["estado_movimento"] == "parado":
        texto = f"Essa pessoa está parada nesse local, bateria {pos['batt']}%."
    else:
        direcao = f" em direção à {pos['poi_cache']}" if pos.get("poi_cache") else ""
        texto = f"Essa pessoa está passando por esse local{direcao}, bateria {pos['batt']}%."

    return jsonify({"detalhes": texto})

# ==============================
# INIT
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
