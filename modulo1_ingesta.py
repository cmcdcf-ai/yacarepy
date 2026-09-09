# =====================================================
# YACARÉPY v2.7 - Detector SEMANAL + Priorización + Capa visible de deforestación
# v2.7: deforestacion.geojson para el visor + credenciales con .strip()
# Costo: $0 | Dependencias: NINGUNA (stdlib Python 3)
# =====================================================
import json, csv, io, math, re, os, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

# ---------------- CREDENCIALES (nunca hardcodeadas en repo público) ----------------
def cargar_credenciales():
    creds = {
        "FIRMS_API_KEY": os.environ.get("FIRMS_API_KEY", ""),
        "TELEGRAM_TOKEN": os.environ.get("TELEGRAM_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }
    try:
        with open("credenciales.json", "r", encoding="utf-8") as f:
            loc = json.load(f)
        for k in creds:
            if not creds[k]:
                creds[k] = str(loc.get(k, ""))
    except Exception:
        pass
    return {k: (v or "").strip() for k, v in creds.items()}

C = cargar_credenciales()

# ---------------- CONFIGURACIÓN ----------------
FUENTES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]
DIAS = 5
OESTE, SUR, ESTE, NORTE = -56, -27, -54, -25
RADIO_MULTISENSOR_M = 1500
VENTANA_MEMORIA_DIAS = 7
VENTANA_SEMANAL_DIAS = 14
VENTANA_BUSQUEDA_DIAS = 45
VENTANA_ALERTAS_DIAS = 60

CODIGOS_ADM2 = {
    "Domingo Martínez de Irala": 3,
    "Los Cedrales": 7,
    "Ñacunday": 11,
    "Naranjal": 12,
    "San Cristóbal": 15,
    "Santa Rita": 16,
    "Santa Rosa del Monday": 17,
}
SIN_CODIGO_OFICIAL = ["Tavapy", "Dr. Raúl Peña"]

CENTROIDES = {
    "Santa Rita": (-25.66, -55.07),
    "Santa Rosa del Monday": (-25.90, -55.15),
    "Dr. Raúl Peña": (-25.50, -55.27),
    "San Cristóbal": (-25.63, -55.25),
    "Naranjal": (-25.83, -55.18),
    "Ñacunday": (-26.15, -54.90),
    "Los Cedrales": (-25.57, -54.95),
    "Tavapy": (-25.73, -54.97),
    "Domingo Martínez de Irala": (-25.85, -54.80),
}

GFW_BASE = "https://globalnaturewatch.org/api/data/dataset"
DS_ALERTAS = "gadm__integrated_alerts__adm2_daily_alerts/latest/query"
DS_TCL_CHANGE = "gadm__tcl__adm2_change/v20260407/query"
DS_TCL_SUMMARY = "gadm__tcl__adm2_summary/v20260407/query"
DS_WHITELIST = "gadm__glad__adm2_whitelist/latest/query"

DIST_URL = ("https://raw.githubusercontent.com/wmgeolab/geoBoundaries/main/"
            "releaseData/gbOpen/PRY/ADM2/geoBoundaries-PRY-ADM2_simplified.geojson")

WL_COLS = [
    ("wdpa_protected_areas__iucn_cat", "wdpa"),
    ("is__ifl_intact_forest_landscapes_2016", "ifl"),
    ("is__umd_regional_primary_forest_2001", "primary_forest"),
    ("sbtn_natural_forests__class", "natural2020"),
    ("is__birdlife_key_biodiversity_areas", "kba"),
    ("is__landmark_indigenous_and_community_lands", "landmark"),
    ("is__gfw_peatlands", "peat"),
]

# ---------------- HTTP ----------------
def http_get(url, timeout=180):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")

def gfw_request(dataset_path, sql):
    url = f"{GFW_BASE}/{dataset_path}/?sql=" + urllib.parse.quote(sql, safe="")
    try:
        return json.loads(http_get(url)).get("data", [])
    except urllib.error.HTTPError as e:
        print(f"[GFW:{dataset_path.split('/')[0][:12]}] HTTP {e.code}: {e.read().decode()[:150]}")
        return None
    except Exception as e:
        print(f"[GFW:{dataset_path.split('/')[0][:12]}] error: {e}")
        return None

# ---------------- UTILIDADES ----------------
def to_bool(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")

def presente(v):
    s = str(v or "")
    return s != "" and s.lower() not in ("none", "null", "false")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def parse_fecha(s):
    try:
        return datetime.fromisoformat(str(s)[:10])
    except Exception:
        return None

def en_poligono(lat, lon, rings):
    outer = rings[0]
    dentro = False
    j = len(outer) - 1
    for i in range(len(outer)):
        xi, yi = outer[i][0], outer[i][1]
        xj, yj = outer[j][0], outer[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            dentro = not dentro
        j = i
    return dentro

def cargar_distritos():
    try:
        data = json.loads(http_get(DIST_URL))
        polys = []
        for f in data.get("features", []):
            name = f["properties"].get("shapeName", "")
            g = f["geometry"]
            if g["type"] == "Polygon":
                polys.append((name, [g["coordinates"]]))
            elif g["type"] == "MultiPolygon":
                polys.append((name, g["coordinates"]))
        print(f"[GEO] Plan A OK: {len(polys)} distritos oficiales cargados")
        return ("oficial", polys)
    except Exception as e:
        print(f"[GEO] Plan A no disponible ({e}); usando Plan B (proximidad)")
        return ("aprox", None)

def etiquetar(lat, lon, modo, polys):
    if modo == "oficial":
        for name, multipol in polys:
            for rings in multipol:
                if en_poligono(lat, lon, rings):
                    return name
        return "Fuera de distritos objetivo"
    mejor, dmin = None, 1e18
    for name, (la, lo) in CENTROIDES.items():
        d = haversine(lat, lon, la, lo)
        if d < dmin:
            dmin, mejor = d, name
    return mejor

def feature(lat, lon, nivel, detalle, distrito, modo, primera, prioridad="MEDIA"):
    sufijo = "" if modo == "oficial" else " (aprox.)"
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            "properties": {"nivel": nivel, "detalle": detalle,
                           "distrito": distrito + sufijo,
                           "prioridad_institucional": prioridad,
                           "coords": f"{round(lat,4)}, {round(lon,4)}",
                           "primera_vista": primera,
                           "generado": datetime.now(timezone.utc).isoformat()}}

# ---------------- CAPA D: FUEGOS ----------------
def fetch_firms(fuente):
    url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
           f"{C['FIRMS_API_KEY']}/{fuente}/{OESTE},{SUR},{ESTE},{NORTE}/{DIAS}")
    try:
        texto = http_get(url)
    except urllib.error.HTTPError as e:
        print(f"[{fuente}] HTTP {e.code}: {e.read().decode()[:200]}")
        return []
    except Exception as e:
        print(f"[{fuente}] no disponible: {e}")
        return []
    pts = []
    for f in csv.DictReader(io.StringIO(texto)):
        try:
            pts.append({"lat": float(f["latitude"]), "lon": float(f["longitude"]),
                        "fecha": f.get("acq_date", ""), "ts": parse_fecha(f.get("acq_date", "")),
                        "fuente": fuente,
                        "brillo": float(f.get("brightness") or f.get("bright_ti4") or 0)})
        except (KeyError, ValueError):
            continue
    return pts

def cruzar_multisensor(detecciones):
    alertas, usadas = [], set()
    for i, d in enumerate(detecciones):
        if i in usadas:
            continue
        usadas.add(i)
        grupo = [d]
        for j, e in enumerate(detecciones):
            if j in usadas or e["fuente"] == d["fuente"]:
                continue
            if (e["ts"] and d["ts"] and abs((e["ts"] - d["ts"]).days) <= 1
                    and haversine(d["lat"], d["lon"], e["lat"], e["lon"]) <= RADIO_MULTISENSOR_M):
                grupo.append(e)
                usadas.add(j)
        sensores = sorted(set(g["fuente"].replace("VIIRS_", "").replace("_NRT", "") for g in grupo))
        if len(sensores) >= 2:
            nivel = "ALTA"
            detalle = (f"FUEGO CONFIRMADO por {len(sensores)} sensores "
                       f"({'+'.join(sensores)}) | {d['fecha']} | brillo={d['brillo']}K")
        else:
            nivel = "SOSPECHA"
            detalle = (f"1 solo sensor ({d['fuente']}) | {d['fecha']} | "
                       f"brillo={d['brillo']}K | requiere confirmación")
        alertas.append((d["lat"], d["lon"], nivel, detalle))
    return alertas

# ---------------- CAPA E ----------------
def fetch_gfw_semanal():
    codes = ",".join(str(c) for c in CODIGOS_ADM2.values())
    desde = (datetime.now() - timedelta(days=VENTANA_BUSQUEDA_DIAS)).strftime("%Y-%m-%d")
    sql = (f"SELECT adm2, gfw_integrated_alerts__date AS d, SUM(alert_area__ha) AS ha, "
           f"gfw_integrated_alerts__confidence AS c FROM data "
           f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes}) "
           f"AND gfw_integrated_alerts__date >= '{desde}' "
           f"GROUP BY adm2, gfw_integrated_alerts__date, gfw_integrated_alerts__confidence")
    rows = gfw_request(DS_ALERTAS, sql)
    if not rows:
        return {}, None
    mx = max(str(r.get("d") or "")[:10] for r in rows)
    f_mx = parse_fecha(mx)
    if not f_mx:
        return {}, None
    inicio = f_mx - timedelta(days=VENTANA_SEMANAL_DIAS)
    por = {}
    for r in rows:
        fd = str(r.get("d") or "")[:10]
        f_fd = parse_fecha(fd)
        if not f_fd or f_fd < inicio:
            continue
        d = por.setdefault(r.get("adm2"), {"ha": 0.0, "ha_alta": 0.0, "ultima": None})
        ha = float(r.get("ha") or 0)
        d["ha"] += ha
        if str(r.get("c", "")).lower() == "high":
            d["ha_alta"] += ha
        if fd and (d["ultima"] is None or fd > d["ultima"]):
            d["ultima"] = fd
    return por, mx

# ---------------- CAPA A ----------------
def fetch_gfw_alertas():
    desde = (datetime.now() - timedelta(days=VENTANA_ALERTAS_DIAS)).strftime("%Y-%m-%d")
    codes = ",".join(str(c) for c in CODIGOS_ADM2.values())
    sql = (f"SELECT adm2, SUM(alert_area__ha) AS ha, SUM(alert__count) AS n, "
           f"gfw_integrated_alerts__confidence AS c FROM data "
           f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes}) "
           f"AND gfw_integrated_alerts__date >= '{desde}' "
           f"GROUP BY adm2, gfw_integrated_alerts__confidence")
    rows = gfw_request(DS_ALERTAS, sql)
    if rows is None:
        return {}
    por = {}
    for r in rows:
        d = por.setdefault(r.get("adm2"), {"ha": 0.0, "n": 0, "ha_alta": 0.0})
        ha = float(r.get("ha") or 0); n = int(r.get("n") or 0)
        d["ha"] += ha; d["n"] += n
        if str(r.get("c", "")).lower() == "high":
            d["ha_alta"] += ha
    return por

# ---------------- CAPAS B+C ----------------
def fetch_gfw_perdida():
    codes = ",".join(str(c) for c in CODIGOS_ADM2.values())
    sql = (f"SELECT adm2, umd_tree_cover_loss__year AS yr, SUM(umd_tree_cover_loss__ha) AS ha "
           f"FROM data "
           f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes}) "
           f"AND umd_tree_cover_density_2000__threshold = 30 "
           f"GROUP BY adm2, umd_tree_cover_loss__year")
    rows = gfw_request(DS_TCL_CHANGE, sql)
    if rows is None:
        return {}, None
    por = {}; anios_set = set()
    for r in rows:
        yr = int(r.get("yr") or 0); ha = float(r.get("ha") or 0)
        if yr:
            por.setdefault(r.get("adm2"), {})[yr] = ha
            anios_set.add(yr)
    anio_rec = max(anios_set) if anios_set else None
    sql_prim = (f"SELECT adm2, umd_tree_cover_loss__year AS yr, SUM(umd_tree_cover_loss__ha) AS ha "
                f"FROM data "
                f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes}) "
                f"AND umd_tree_cover_density_2000__threshold = 30 "
                f"AND is__umd_regional_primary_forest_2001 = 'true' "
                f"GROUP BY adm2, umd_tree_cover_loss__year")
    rows_prim = gfw_request(DS_TCL_CHANGE, sql_prim)
    prim = {}
    if rows_prim:
        for r in rows_prim:
            yr = int(r.get("yr") or 0); ha = float(r.get("ha") or 0)
            if yr:
                prim.setdefault(r.get("adm2"), {})[yr] = ha
    return {"general": por, "primario": prim, "anio": anio_rec}

def fetch_gfw_extension():
    codes = ",".join(str(c) for c in CODIGOS_ADM2.values())
    sql = (f"SELECT adm2, SUM(umd_tree_cover_extent_2000__ha) AS ext FROM data "
           f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes}) "
           f"AND umd_tree_cover_density_2000__threshold = 30 GROUP BY adm2")
    rows = gfw_request(DS_TCL_SUMMARY, sql)
    if rows is None:
        return {}
    return {r.get("adm2"): float(r.get("ext") or 0) for r in rows}

# ---------------- WHITELIST ----------------
def fetch_whitelist():
    codes = ",".join(str(c) for c in CODIGOS_ADM2.values())
    cols = list(WL_COLS)
    rows = []
    for intento in range(len(WL_COLS) + 1):
        select = ", ".join(f"{orig} AS {alias}" for orig, alias in cols)
        sql = (f"SELECT adm2, {select} FROM data "
               f"WHERE iso = 'PRY' AND adm1 = 2 AND adm2 IN ({codes})")
        url = f"{GFW_BASE}/{DS_WHITELIST}/?sql=" + urllib.parse.quote(sql, safe="")
        try:
            rows = json.loads(http_get(url)).get("data", [])
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            m = re.search(r'column\s+\\?"?(\w+)\\?"?\s+does not exist', body)
            if not m:
                print(f"[WHITELIST] HTTP {e.code} sin columna identificable; se omite")
                return {}
            mala = m.group(1)
            antes = len(cols)
            cols = [(o, a) for (o, a) in cols if o != mala and a != mala]
            if len(cols) == antes or not cols:
                print(f"[WHITELIST] no se pudo ajustar el esquema ({mala}); se omite")
                return {}
            print(f"[WHITELIST] el servidor no tiene la columna '{mala}'; se excluye y reintenta")
        except Exception as e:
            print(f"[WHITELIST] error: {e}; se omite")
            return {}
    wl = {}
    for r in rows:
        c = r.get("adm2")
        if c is None:
            continue
        d = wl.setdefault(c, {"wdpa": "", "ifl": False, "primary": False,
                              "natural": "", "kba": False, "landmark": False, "peat": False})
        raw_w = r.get("wdpa")
        if raw_w is not None:
            sw = str(raw_w)
            if sw.lower() in ("true", "false"):
                if sw.lower() == "true" and not d["wdpa"]:
                    d["wdpa"] = "PRESENTE"
            elif presente(sw) and not d["wdpa"]:
                d["wdpa"] = sw
        if to_bool(r.get("ifl")):
            d["ifl"] = True
        if to_bool(r.get("primary_forest")):
            d["primary"] = True
        v2 = str(r.get("natural2020") or "")
        if presente(v2) and not d["natural"]:
            d["natural"] = v2
        if to_bool(r.get("kba")):
            d["kba"] = True
        if to_bool(r.get("landmark")):
            d["landmark"] = True
        if to_bool(r.get("peat")):
            d["peat"] = True
    print(f"[WHITELIST] esquema final: {', '.join(a for _, a in cols)}")
    return wl

def clasificar_prioridad(wl):
    if not wl:
        return ("MEDIA", ["sin clasificación"])
    tags = []
    if wl.get("wdpa"):
        cat = "" if wl["wdpa"] == "PRESENTE" else f" cat.{wl['wdpa']}"
        tags.append(f"Área Protegida WDPA{cat} en el distrito (verif. puntual pend.)")
    if wl.get("ifl"):
        tags.append("Bosque Intacto en el distrito (verif. puntual pend.)")
    if tags:
        return ("CRITICA", tags)
    if wl.get("primary"):
        tags.append("Bosque Primario")
    if wl.get("natural"):
        tags.append(f"Bosque Natural ({wl['natural']})")
    if wl.get("kba"):
        tags.append("KBA BirdLife")
    if wl.get("landmark"):
        tags.append("Tierra Indígena/Comunitaria")
    if wl.get("peat"):
        tags.append("Turbera")
    if tags:
        return ("ALTA", tags)
    return ("MEDIA", ["vegetación general"])

# ---------------- TELEGRAM ----------------
def enviar_telegram(texto):
    if not C["TELEGRAM_TOKEN"] or not C["TELEGRAM_CHAT_ID"]:
        print("[TELEGRAM] no configurado (falta credencial)")
        return False
    url = f"https://api.telegram.org/bot{C['TELEGRAM_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": C["TELEGRAM_CHAT_ID"], "text": texto}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ok = json.loads(r.read().decode()).get("ok")
        print(f"[TELEGRAM] enviado: {ok}")
        return ok
    except Exception as e:
        print(f"[TELEGRAM] fallo: {e}")
        return False

# ---------------- MAIN ----------------
def main():
    hoy = datetime.now().strftime("%Y-%m-%d")
    print("=" * 64)
    print(f"YACARÉPY v2.7 | Detector SEMANAL + Capa visible | {hoy}")
    print("=" * 64)
    if not C["FIRMS_API_KEY"]:
        print("[ERROR] Falta FIRMS_API_KEY (entorno o credenciales.json)")
        return

    print("\n── CAPA D: FUEGOS NASA FIRMS (latencia ~horas) ──")
    todas = []
    for fu in FUENTES:
        pts = fetch_firms(fu)
        print(f"  [{fu}] detecciones: {len(pts)}")
        todas.extend(pts)
    if not todas:
        enviar_telegram(f"🐊 YACARÉPY v2.7 — {hoy}\n⚠️ Fuentes de fuego sin datos. "
                        f"Se conserva el último reporte válido.")
        return

    print("\n── WHITELIST: Priorización jurisdiccional ──")
    wl = fetch_whitelist()
    nombre_por_cod = {c: n for n, c in CODIGOS_ADM2.items()}
    prio = {}
    if wl:
        for nom, c in CODIGOS_ADM2.items():
            p, tags = clasificar_prioridad(wl.get(c))
            prio[nom] = (p, tags)
            print(f"  {nom:<30} {p:<8} {', '.join(tags)}")
    else:
        print("  (whitelist no disponible; prioridad MEDIA)")
        prio = {nom: ("MEDIA", ["sin clasificación"]) for nom in CODIGOS_ADM2}

    crudas = cruzar_multisensor(todas)
    modo, polys = cargar_distritos()
    nuevas_hoy = []
    for (lat, lon, niv, det) in crudas:
        dist = etiquetar(lat, lon, modo, polys).replace(" (aprox.)", "")
        if dist == "Fuera de distritos objetivo":
            dist = "Fuera"
        p, _ = prio.get(dist, ("MEDIA", [""]))
        nuevas_hoy.append(feature(lat, lon, niv, det, dist, modo, hoy, p))

    try:
        with open("alertas.geojson", "r", encoding="utf-8") as f:
            viejas = json.load(f).get("features", [])
    except Exception:
        viejas = []
    corte = datetime.now() - timedelta(days=VENTANA_MEMORIA_DIAS)
    coords_hoy = set(a["properties"]["coords"] for a in nuevas_hoy)
    acumuladas = []
    for a in viejas:
        f_pv = parse_fecha(a["properties"].get("primera_vista", hoy))
        if f_pv and f_pv < corte:
            continue
        if a["properties"]["coords"] not in coords_hoy:
            acumuladas.append(a)
    merged = nuevas_hoy + acumuladas
    with open("alertas.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": merged}, f, ensure_ascii=False)

    altas = sum(1 for a in merged if a["properties"]["nivel"] == "ALTA")
    criticas = sum(1 for a in merged if a["properties"]["nivel"] == "ALTA"
                   and a["properties"].get("prioridad_institucional") == "CRITICA")
    print(f"\n── RESUMEN FUEGOS 7 DÍAS ──")
    print(f"  {len(merged)} alertas | {altas} ALTA | {criticas} ALTA en distritos CRÍTICOS")
    fuegos_por = {}
    for a in merged:
        d = a["properties"]["distrito"].replace(" (aprox.)", "")
        t, al = fuegos_por.get(d, (0, 0))
        fuegos_por[d] = (t + 1, al + (a["properties"]["nivel"] == "ALTA"))
    for d, (t, al) in sorted(fuegos_por.items(), key=lambda x: -x[1][0]):
        p, _ = prio.get(d, ("—", []))
        print(f"    {d:<28} {t:>2} ({al} ALTA) [{p}]")

    print(f"\n── CAPA E: Perturbación oficial (últimos 14 d disponibles) ──")
    sem, corte_oficial = fetch_gfw_semanal()
    if corte_oficial:
        lat_d = (datetime.now() - parse_fecha(corte_oficial)).days
        print(f"   Dato oficial más reciente: {corte_oficial} (latencia {lat_d} días)")
        for c, d in sorted(sem.items(), key=lambda x: -x[1]["ha"]):
            nom = nombre_por_cod.get(c, f"adm2={c}")
            print(f"   {nom:<28} {d['ha']:>7.1f} ha | alta {d['ha_alta']:>7.1f} | última {d['ultima']}")
    else:
        print("   (sin datos oficiales recientes)")

    print(f"\n── CAPA A: Perturbación {VENTANA_ALERTAS_DIAS} d (tendencia) ──")
    alertas_of = fetch_gfw_alertas()
    if alertas_of:
        for c, d in sorted(alertas_of.items(), key=lambda x: -x[1]["ha"]):
            nom = nombre_por_cod.get(c, f"adm2={c}")
            print(f"   {nom}: {d['ha']:.1f} ha (alta: {d['ha_alta']:.1f})")

    print(f"\n── CAPAS B+C: Bosque anual (latencia 12-15 m) ──")
    tcl = fetch_gfw_perdida(); ext = fetch_gfw_extension()
    yr = tcl["anio"]
    if yr:
        print(f"   Año más reciente: {yr}")
        for nom, c in CODIGOS_ADM2.items():
            b = ext.get(c, 0); pt = tcl["general"].get(c, {}).get(yr, 0); pp = tcl["primario"].get(c, {}).get(yr, 0)
            print(f"   {nom:<28} base {b:>8.1f} | pérd {pt:>7.1f} | primario {pp:>6.1f}")

    print("\n── 🚨 CAMBIO DE USO ACTIVO (ventana semanal oficial) ──")
    cambio = []
    for nom, c in CODIGOS_ADM2.items():
        s = sem.get(c)
        fa = fuegos_por.get(nom, (0, 0))[1]
        if s and s["ha_alta"] > 0 and fa > 0:
            p, tags = prio[nom]
            cambio.append((nom, s["ha_alta"], s["ultima"], fa, p))
    if cambio:
        for nom, ha, ult, fa, p in cambio:
            print(f"   🚨 {nom}: {ha:.1f} ha oficiales (últ. {ult}) + {fa} fuegos ALTA | {p}")
    else:
        print("   (sin cruces semanales)")

    print("\n── 🚨 DEFORESTACIÓN BOSQUE PRIMARIO (anual) ──")
    defor = []
    if yr:
        for nom, c in CODIGOS_ADM2.items():
            ha_pr = tcl["primario"].get(c, {}).get(yr, 0)
            fa = fuegos_por.get(nom, (0, 0))[1]
            if ha_pr > 0 and fa > 0:
                defor.append((nom, ha_pr, fa, yr))
    if defor:
        for nom, ha, fa, y in defor:
            print(f"   🚨 {nom}: {ha:.1f} ha primario ({y}) + {fa} fuegos ALTA")
    else:
        print("   (sin cruces)")
    print(f"   Cobertura oficial: {len(CODIGOS_ADM2)}/9 (sin código: {', '.join(SIN_CODIGO_OFICIAL)})")

    # ----- CAPA VISIBLE: deforestación oficial por distrito para el visor -----
    defor_feats = []
    for nom, c in CODIGOS_ADM2.items():
        s = sem.get(c)
        if not s:
            continue
        p, tags = prio[nom]
        cruce = any(x[0] == nom for x in cambio)
        la, lo = CENTROIDES[nom]
        defor_feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lo, la]},
            "properties": {"distrito": nom, "ha_14d": round(s["ha"], 1),
                           "ha_alta": round(s["ha_alta"], 1), "ultima": s["ultima"],
                           "prioridad": p, "cruce_fuego": cruce,
                           "fuente": "GFW Integrated Alerts (oficial)",
                           "latencia_dias": (datetime.now() - parse_fecha(corte_oficial)).days if corte_oficial else None}
        })
    with open("deforestacion.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": defor_feats}, f, ensure_ascii=False)
    print(f"[OUT] deforestacion.geojson -> {len(defor_feats)} distritos con pérdida oficial")

    # ----- BOLETÍN -----
    lat_txt = f" | dato oficial hasta {corte_oficial}" if corte_oficial else ""
    lineas = [f"🐊 YACARÉPY v2.7 — {hoy}",
              f"🔥 7d: {len(merged)} | 🔴 {altas} ALTA | ⚠️ {criticas} en distritos CRÍTICOS{lat_txt}", "",
              "── 🚨 CAMBIO DE USO ACTIVO (semanal) ──"]
    if cambio:
        for nom, ha, ult, fa, p in cambio[:4]:
            lineas.append(f"  {nom}: {ha:.1f} ha (últ. {ult}) + {fa} fuegos | {p}")
    else:
        lineas.append("  (sin cruces semanales)")
    lineas.append("")
    lineas.append("── ⚠️ ALTA en distritos con área protegida ──")
    crit_list = [a for a in merged if a["properties"]["nivel"] == "ALTA"
                 and a["properties"].get("prioridad_institucional") == "CRITICA"]
    if crit_list:
        for a in crit_list[:3]:
            p = a["properties"]
            lineas.append(f"  {p['distrito']}: {p['detalle'][:55]}")
        lineas.append("  (verif. puntual dentro del área: pendiente)")
    else:
        lineas.append("  (ninguna)")
    lineas.append("")
    lineas.append(f"── Bosque primario {yr or '?'} ──")
    if defor:
        for nom, ha, fa, y in defor[:3]:
            lineas.append(f"  {nom}: {ha:.1f} ha + {fa} fuegos")
    else:
        lineas.append("  (sin cruces anuales)")
    lineas.append(f"\nℹ️ Cobertura oficial {len(CODIGOS_ADM2)}/9. Latencias: fuego h | oficial hasta {corte_oficial or 'n/d'} | bosque 12-15 m.")
    enviar_telegram("\n".join(lineas))

if __name__ == "__main__":
    main()