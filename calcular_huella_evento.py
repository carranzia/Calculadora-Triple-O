"""
Calculadora de Huella de Carbono — Premios Madrid Alimenta 2026
Formato entrada : Google Forms export (XLSX o CSV)
Geocodificación : OpenRouteService API
Factores        : DEFRA 2023
"""

import os
import sys
import time
import math
import re
import requests
import pandas as pd
from dotenv import load_dotenv

# ── UTF-8 en Windows ──────────────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Configuración ─────────────────────────────────────────────────────────────
load_dotenv()
ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    sys.exit("❌  Falta ORS_API_KEY en el fichero .env")

VENUE = {
    "lat": 40.4169,
    "lon": -3.7035,
    "nombre": "Real Casa de Correos, Puerta del Sol 7, 28013 Madrid",
}

# ── Factores DEFRA 2023 (kg CO₂e / km) ───────────────────────────────────────
FACTORES = {
    "taxi":      0.19,
    "gasolina":  0.18,   # coche gasolina o diésel (mismo factor DEFRA)
    "hibrido":   0.12,
    "electrico": 0.05,
    "tren":      0.035,
    "metro":     0.03,
    "autobus":   0.06,
    "avion_corto": 0.255,  # < 1 500 km, con forzamiento radiativo (DEFRA 2023)
    "avion_largo": 0.195,  # ≥ 1 500 km
    "pie":       0.00,
}

# Factores alojamiento (kg CO₂e / noche)
ALOJAMIENTO = {
    "hotel":       20.0,
    "apartamento": 15.0,
    "familiares":   0.0,   # sin emisiones comerciales
    "otro":        20.0,   # conservador
}

# Factores transporte local alojamiento → venue (kg CO₂e / km)
FACTORES_LOCAL = {
    "pie":     0.00,
    "metro":   0.03,
    "autobus": 0.06,
    "taxi":    0.19,
    "coche":   0.18,
}

# Distancia fija asumida para tramo secundario (último tramo urbano, km ida)
KM_SECUNDARIO = 5.0

# Distancia fija asumida para transporte local alojamiento → venue (km ida)
KM_LOCAL = 3.0

# ── Normalización de transportes ─────────────────────────────────────────────

def normalizar_transporte(texto: str) -> str:
    """Mapea el texto del formulario a una clave de FACTORES."""
    t = str(texto).lower().strip()
    if not t or t in ("nan", "none", "-", ""):
        return "pie"
    # Orden importa: más específico primero
    if "avión" in t or "avion" in t or "avi" in t:
        return "avion"          # clave genérica; factor elegido por distancia
    if "taxi" in t or "vtc" in t:
        return "taxi"
    if "eléctrico" in t or "electrico" in t:
        return "electrico"
    if "híbrido" in t or "hibrido" in t:
        return "hibrido"
    if "gasolina" in t or "diésel" in t or "diesel" in t or "combustión" in t or "combustion" in t:
        return "gasolina"
    if "tren" in t or "ave" in t or "cercan" in t or "renfe" in t:
        return "tren"
    if "metro" in t or "tranvía" in t or "tranvia" in t:
        return "metro"
    if "autobús" in t or "autobus" in t or "interurban" in t or "bus" in t:
        return "autobus"
    if "pie" in t or "bicicleta" in t or "bici" in t or "andando" in t or "caminando" in t:
        return "pie"
    if "coche" in t or "vehículo" in t or "vehiculo" in t or "carro" in t:
        return "gasolina"
    return "gasolina"           # fallback conservador

def normalizar_local(texto: str) -> str:
    """Mapea transporte alojamiento→venue a FACTORES_LOCAL."""
    t = str(texto).lower().strip()
    if "pie" in t or "bici" in t:
        return "pie"
    if "metro" in t or "tranvía" in t or "tranvia" in t:
        return "metro"
    if "autobús" in t or "autobus" in t or "bus" in t:
        return "autobus"
    if "taxi" in t or "vtc" in t:
        return "taxi"
    if "coche" in t or "carro" in t or "vehículo" in t:
        return "coche"
    return "pie"

def normalizar_alojamiento(texto: str) -> str:
    """Mapea tipo de alojamiento a clave de ALOJAMIENTO."""
    t = str(texto).lower().strip()
    if "hotel" in t:
        return "hotel"
    if "apart" in t or "turístic" in t or "turistico" in t or "piso" in t or "airbnb" in t:
        return "apartamento"
    if "familiar" in t or "amig" in t or "casa" in t:
        return "familiares"
    if t and t not in ("nan", "none", "-", ""):
        return "otro"
    return "hotel"              # default conservador

def extraer_ocupantes(texto: str) -> int:
    """Devuelve el número de ocupantes del coche (1-4)."""
    t = str(texto).lower().strip()
    if "4" in t or "más" in t or "mas" in t:
        return 4
    if "3" in t:
        return 3
    if "2" in t:
        return 2
    return 1   # "solo yo" o desconocido

def extraer_atribucion(texto: str) -> float:
    """Factor de atribución: 1.0 si viaje exclusivo, 0.5 si parcial, 0.0 si no."""
    t = str(texto).lower().strip()
    if "parcial" in t:
        return 0.5
    if "no" == t or t.startswith("no "):
        return 0.0
    return 1.0   # "sí exclusivamente" o desconocido → 100%

def extraer_noches(valor) -> float:
    """Extrae el número de noches del campo correspondiente."""
    try:
        return max(0.0, float(str(valor).strip().split()[0]))
    except Exception:
        return 1.0

def es_combinado(texto: str) -> bool:
    t = str(texto).lower().strip()
    return t in ("sí", "si", "yes", "1", "true", "s")

# ── Detección flexible de columnas Google Forms ───────────────────────────────

def buscar_col(cols: list[str], *keywords: str, excluir_sufijo_num: bool = False) -> str | None:
    """
    Devuelve el nombre de la primera columna que contenga TODAS las keywords
    (case-insensitive). Si excluir_sufijo_num=True ignora columnas que terminen
    en dígito (p.ej. duplicadas de Google Forms como 'campo?2').
    """
    for col in cols:
        cl = col.lower().strip()
        if excluir_sufijo_num and cl and cl[-1].isdigit():
            continue
        if all(kw.lower() in cl for kw in keywords):
            return col
    return None

def detectar_columnas(df: pd.DataFrame) -> dict:
    """
    Busca las columnas del formulario Google Forms con nombre flexible.
    Lanza un error descriptivo si alguna columna obligatoria no se encuentra.
    """
    cols = list(df.columns)
    mapping = {}

    # ── Columnas obligatorias ─────────────────────────────────────────────────
    # Cada entrada es lista de tuplas-de-keywords; se prueba en orden.
    # Se incluyen tanto patrones del formato nuevo (Google Forms)
    # como los del formato antiguo para compatibilidad.
    obligatorias = {
        "origen": [
            # Nuevo formato Google Forms
            ("ciudad", "origen"),
            ("municipio", "origen"),
            ("ciudad/municipio",),
            # Formato antiguo: "Indica el punto de inicio del trayecto"
            ("punto de inicio",),
            ("inicio del trayecto",),
            ("inicio",),
        ],
        "transp_principal": [
            # Nuevo
            ("transporte", "principal"),
            ("medio", "principal"),
            # Antiguo: "Que medio o medios de transporte has utilizado?"
            # (excluimos la copia con "2" al final usando búsqueda exacta)
            ("medios de transporte",),
            ("medio", "transporte"),
        ],
        "exclusivo": [
            ("exclusivo",), ("exclusivamente",),
        ],
    }
    for campo, alternativas in obligatorias.items():
        encontrado = None
        for kws in alternativas:
            # Para el transporte principal excluimos columnas con sufijo numérico
            excl_num = (campo == "transp_principal")
            encontrado = buscar_col(cols, *kws, excluir_sufijo_num=excl_num)
            if encontrado:
                break
        if not encontrado:
            if campo == "exclusivo":
                # Columna nueva: si no existe en el formato antiguo la ignoramos
                # y asumimos 100% atribución (valor "Sí exclusivamente")
                mapping[campo] = None
            else:
                sys.exit(
                    f"❌  No se encontró la columna '{campo}' en el fichero.\n"
                    f"    Columnas disponibles: {cols}"
                )
        else:
            mapping[campo] = encontrado

    # ── Columnas opcionales (con fallback) ────────────────────────────────────
    opcionales = {
        "ocupantes":        [("ocupantes",), ("cuántas personas",), ("cuantas personas",)],
        "combinado":        [("combinado",), ("ha combinado",), ("combina",),
                             ("cuantos trayectos",), ("trayectos",)],
        "transp_secundario":[("secundario",), ("medio secundario",),
                             ("medios de transporte",)],   # col duplicada del formato antiguo
        "aloj_needed":      [("alojamiento", "necesit"), ("necesitó alojamiento",),
                             ("necesito alojamiento",), ("necsitado alojamiento",),
                             ("necesitado alojamiento",), ("alojamiento",)],
        "aloj_tipo":        [("tipo", "alojamiento"), ("tipo de alojamiento",)],
        "noches":           [("noches",), ("pernoctadas",),
                             ("tiempo", "alojamiento"), ("llegado", "alojamiento"),
                             ("desde tu alojamiento",)],
        "transp_local":     [("desde alojamiento",), ("alojamiento al venue",),
                             ("transporte desde",)],
    }
    for campo, alternativas in opcionales.items():
        encontrado = None
        for kws in alternativas:
            encontrado = buscar_col(cols, *kws)
            if encontrado:
                break
        mapping[campo] = encontrado   # puede ser None → campo ausente

    return mapping

# ── Geocodificación ───────────────────────────────────────────────────────────

GEO_CACHE: dict = {}

ORIGENES_INVALIDOS = {"casa", "coche", "vehiculo", "vehículo", "taxi", "avión", "avion", ""}

CORRECCIONES = {
    "corabanchem": "Carabanchel, Madrid",
}

def geocodificar(origen: str) -> tuple[float, float] | None:
    origen_limpio = str(origen).strip()
    clave = origen_limpio.lower()

    if clave in GEO_CACHE:
        return GEO_CACHE[clave]

    if clave in CORRECCIONES:
        origen_limpio = CORRECCIONES[clave]
        clave = origen_limpio.lower()

    if clave in ORIGENES_INVALIDOS or len(clave) < 3:
        GEO_CACHE[clave] = None
        return None

    query = origen_limpio
    if not any(w in clave for w in ("madrid", "españa", "spain", "barcelona", "bilbao",
                                     "sevilla", "valencia", "zaragoza")):
        query = f"{origen_limpio}, España"

    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query, "boundary.country": "ES", "size": 1}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        resultado = (
            (features[0]["geometry"]["coordinates"][1],
             features[0]["geometry"]["coordinates"][0])
            if features else None
        )
    except Exception as e:
        print(f"   ⚠  Error geocodificando '{origen_limpio}': {e}")
        resultado = None

    GEO_CACHE[clave] = resultado
    time.sleep(0.3)
    return resultado

# ── Cálculo de distancia ──────────────────────────────────────────────────────

DIST_CACHE: dict = {}

def distancia_carretera_km(lat: float, lon: float) -> float | None:
    clave = f"{lat:.4f},{lon:.4f}"
    if clave in DIST_CACHE:
        return DIST_CACHE[clave]

    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    body = {"coordinates": [[lon, lat], [VENUE["lon"], VENUE["lat"]]]}
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        resultado = resp.json()["routes"][0]["summary"]["distance"] / 1000.0
    except Exception as e:
        print(f"   ⚠  Error ruta ({lat},{lon}): {e} — usando distancia aérea")
        resultado = haversine(lat, lon, VENUE["lat"], VENUE["lon"])

    DIST_CACHE[clave] = resultado
    time.sleep(0.3)
    return resultado

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# ── Safeguards de datos anómalos ──────────────────────────────────────────────
#
# Cada regla se define como un dict con:
#   aplica   : función (clave, dist) → bool
#   accion   : "reclasificar" | "excluir" | "revisar"
#   nuevo    : nueva clave si accion == "reclasificar" (str) o None
#   tipo     : código de anomalía (str)
#   mensaje  : descripción human-readable para informes
#
# Las reglas se evalúan EN ORDEN; la primera que aplica se ejecuta.
# Si la acción es "excluir", se detiene el procesamiento posterior.

SAFEGUARDS: list[dict] = [
    {   # Regla 1
        "aplica":   lambda k, d: k == "taxi" and d is not None and d > 100,
        "accion":   "reclasificar",
        "nuevo":    "gasolina",
        "tipo":     "TAXI_DIST>100km",
        "mensaje":  "Taxi con distancia > 100 km → reclasificado como Coche (gasolina/diésel)",
    },
    {   # Regla 2
        "aplica":   lambda k, d: k == "metro" and d is not None and d > 80,
        "accion":   "excluir",
        "nuevo":    None,
        "tipo":     "METRO_DIST>80km",
        "mensaje":  "Metro/Tranvía con distancia > 80 km → anomalía grave, excluido del cálculo de transporte",
    },
    {   # Regla 3
        "aplica":   lambda k, d: k == "pie" and d is not None and d > 20,
        "accion":   "reclasificar",
        "nuevo":    "metro",
        "tipo":     "PIE_DIST>20km",
        "mensaje":  "A pie/Bicicleta con distancia > 20 km → reclasificado como Metro/Tranvía",
    },
    {   # Regla 4
        "aplica":   lambda k, d: k == "autobus" and d is not None and d > 500,
        "accion":   "revisar",
        "nuevo":    None,
        "tipo":     "AUTOBUS_DIST>500km",
        "mensaje":  "Autobús interurbano con distancia > 500 km → marcado para revisión manual",
    },
    {   # Regla 5 (se aplica después de las anteriores, sobre la clave ya actualizada)
        "aplica":   lambda k, d: k not in ("avion", "pie") and d is not None and d > 1500,
        "accion":   "reclasificar",
        "nuevo":    "avion",
        "tipo":     "DIST>1500km_NO_AVION",
        "mensaje":  "Distancia > 1 500 km con medio no-avión → reclasificado como Avión",
    },
]


def aplicar_safeguards(
    clave: str, dist: float | None, fila_id: int, origen: str
) -> tuple[str, bool, list[dict]]:
    """
    Evalúa las reglas de safeguard en orden.

    Devuelve:
        clave_final  : clave de transporte definitiva (puede haber cambiado)
        excluido     : True si la fila debe excluirse del cálculo de transporte
        anomalias    : lista de dicts con la info de cada anomalía detectada
    """
    anomalias: list[dict] = []
    excluido = False
    clave_actual = clave

    for regla in SAFEGUARDS:
        if not regla["aplica"](clave_actual, dist):
            continue

        entrada = {
            "id":              fila_id,
            "origen":          origen,
            "clave_original":  clave,
            "clave_final":     regla["nuevo"] if regla["nuevo"] else clave_actual,
            "distancia_km":    dist,
            "tipo":            regla["tipo"],
            "accion":          regla["accion"],
            "descripcion":     regla["mensaje"],
        }
        anomalias.append(entrada)

        if regla["accion"] == "reclasificar":
            clave_actual = regla["nuevo"]
            entrada["clave_final"] = clave_actual
        elif regla["accion"] == "excluir":
            excluido = True
            break          # no evaluar más reglas si se excluye
        # "revisar": no cambia clave ni excluye, solo registra

    return clave_actual, excluido, anomalias


# ── Procesamiento de cada fila ────────────────────────────────────────────────

def procesar_fila(fila: pd.Series, cols: dict, fila_id: int) -> dict:
    def get(campo, default=""):
        col = cols.get(campo)
        return str(fila[col]).strip() if col and col in fila.index else default

    origen              = get("origen")
    transp_princ_raw    = get("transp_principal")
    ocupantes_raw       = get("ocupantes", "Solo yo")
    combinado_raw       = get("combinado", "No")
    transp_sec_raw      = get("transp_secundario", "")
    aloj_needed_raw     = get("aloj_needed", "No")
    aloj_tipo_raw       = get("aloj_tipo", "")
    noches_raw          = fila[cols["noches"]] if cols.get("noches") and cols["noches"] in fila.index else 0
    transp_local_raw    = get("transp_local", "A pie")
    exclusivo_raw       = get("exclusivo", "Sí exclusivamente")

    clave_principal = normalizar_transporte(transp_princ_raw)
    ocupantes       = extraer_ocupantes(ocupantes_raw)
    combinado       = es_combinado(combinado_raw)
    factor_atrib    = extraer_atribucion(exclusivo_raw)

    resultado = {
        "id":                   fila_id,
        "origen":               origen,
        "transporte_principal": transp_princ_raw,
        "transporte_clave":     clave_principal,
        "transporte_secundario": transp_sec_raw if combinado else "",
        "ocupantes":            ocupantes_raw,
        "factor_ocupacion":     ocupantes,
        "viaje_exclusivo":      exclusivo_raw,
        "factor_atribucion":    factor_atrib,
        "lat":                  None,
        "lon":                  None,
        "distancia_km":         None,
        "transporte_original":  clave_principal,   # clave antes de safeguards
        "anomalia_tipo":        "",
        "anomalia_accion":      "",
        "co2_principal":        0.0,
        "co2_secundario":       0.0,
        "co2_transporte":       0.0,   # (principal+secundario)×atrib
        "co2_local":            0.0,   # alojamiento→venue
        "co2_alojamiento":      0.0,
        "alojamiento_tipo":     "",
        "noches":               0,
        "co2_total":            0.0,
        "nota":                 "",
    }

    # ── Geocodificación ───────────────────────────────────────────────────────
    coords = geocodificar(origen)
    if coords:
        resultado["lat"], resultado["lon"] = coords
        # Avión → distancia aérea; resto → carretera
        if clave_principal == "avion":
            dist_raw = haversine(resultado["lat"], resultado["lon"], VENUE["lat"], VENUE["lon"])
        else:
            dist_raw = distancia_carretera_km(resultado["lat"], resultado["lon"])
        if dist_raw is not None:
            resultado["distancia_km"] = round(dist_raw, 2)
    else:
        resultado["nota"] += "Origen no geocodificable. "

    # ── Safeguards ────────────────────────────────────────────────────────────
    dist = resultado["distancia_km"]
    clave_principal, excluido_transp, anomalias = aplicar_safeguards(
        clave_principal, dist, fila_id, origen
    )
    resultado["transporte_clave"] = clave_principal   # actualizar con posible reclasificación

    if anomalias:
        tipos   = " | ".join(a["tipo"] for a in anomalias)
        acciones = " | ".join(a["accion"] for a in anomalias)
        msgs    = " / ".join(a["descripcion"] for a in anomalias)
        resultado["anomalia_tipo"]   = tipos
        resultado["anomalia_accion"] = acciones
        resultado["nota"] += f"[SAFEGUARD] {msgs}. "
        for a in anomalias:
            print(f"   ⚠  #{fila_id} SAFEGUARD ({a['tipo']}): {a['descripcion']}")

    if excluido_transp:
        # Excluir emisiones de transporte; alojamiento se calcula igualmente
        resultado["co2_principal"]  = 0.0
        resultado["co2_transporte"] = 0.0

    # ── CO₂ transporte principal (ida + vuelta) ───────────────────────────────
    if not excluido_transp and dist is not None:
        if clave_principal == "avion":
            factor_p = FACTORES["avion_largo"] if dist >= 1500 else FACTORES["avion_corto"]
        else:
            factor_p = FACTORES[clave_principal]
            # Factor de ocupación: solo aplica a coches privados
            if clave_principal in {"gasolina", "hibrido", "electrico"} and ocupantes > 1:
                factor_p = factor_p / ocupantes
                resultado["nota"] += f"Ocupación {ocupantes} → factor/{ocupantes}. "
        resultado["co2_principal"] = round(dist * 2 * factor_p, 3)
    elif not excluido_transp:
        resultado["nota"] += "Sin distancia → CO₂ transporte=0. "

    # ── CO₂ transporte secundario (tramo fijo de último tramo urbano) ─────────
    if combinado and transp_sec_raw:
        clave_sec = normalizar_transporte(transp_sec_raw)
        factor_sec = FACTORES.get(clave_sec, 0.0)
        if clave_sec == "avion":
            factor_sec = FACTORES["avion_corto"]
        co2_sec = round(KM_SECUNDARIO * 2 * factor_sec, 3)
        resultado["co2_secundario"] = co2_sec
        resultado["nota"] += (
            f"Secundario '{clave_sec}' ({KM_SECUNDARIO*2:.0f} km fijos asumidos). "
        )

    # ── CO₂ transporte total × atribución ─────────────────────────────────────
    resultado["co2_transporte"] = round(
        (resultado["co2_principal"] + resultado["co2_secundario"]) * factor_atrib, 3
    )
    if factor_atrib < 1.0:
        resultado["nota"] += f"Atribución {int(factor_atrib*100)}% (viaje parcial). "

    # ── Alojamiento ───────────────────────────────────────────────────────────
    if aloj_needed_raw.lower() in ("sí", "si", "yes", "1", "true"):
        noches = extraer_noches(noches_raw)
        tipo   = normalizar_alojamiento(aloj_tipo_raw)
        factor_aloj = ALOJAMIENTO[tipo]
        resultado["alojamiento_tipo"] = tipo
        resultado["noches"]           = int(noches)
        resultado["co2_alojamiento"]  = round(factor_aloj * noches * factor_atrib, 2)

        # Transporte local alojamiento → venue (ida×2 × noches)
        clave_local  = normalizar_local(transp_local_raw)
        factor_local = FACTORES_LOCAL.get(clave_local, 0.0)
        resultado["co2_local"] = round(KM_LOCAL * 2 * noches * factor_local, 3)

        if tipo == "familiares":
            resultado["nota"] += "Alojamiento en casa de familiares → 0 kg CO₂/noche. "

    # ── Total ─────────────────────────────────────────────────────────────────
    resultado["co2_total"] = round(
        resultado["co2_transporte"]
        + resultado["co2_local"]
        + resultado["co2_alojamiento"],
        3
    )
    return resultado

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Buscar fichero de datos
    candidatos = [
        f for f in os.listdir(".")
        if f.lower().endswith((".xlsx", ".csv")) and "huella" in f.lower()
    ]
    # También aceptar cualquier xlsx/csv si solo hay uno
    if not candidatos:
        candidatos = [f for f in os.listdir(".") if f.lower().endswith((".xlsx", ".csv"))
                      and "resultados" not in f.lower()]

    if not candidatos:
        sys.exit("❌  No se encontró ningún fichero de datos (.xlsx / .csv) en el directorio.")

    # Preferir xlsx
    fichero = next((f for f in candidatos if f.lower().endswith(".xlsx")), candidatos[0])
    print(f"\n  📂  Leyendo: {fichero}")

    if fichero.lower().endswith(".xlsx"):
        df_raw = pd.read_excel(fichero)
    else:
        df_raw = pd.read_csv(fichero, sep=None, engine="python", encoding="utf-8-sig")

    # Eliminar filas completamente vacías
    df_raw = df_raw.dropna(how="all").reset_index(drop=True)

    # Detectar columnas
    cols = detectar_columnas(df_raw)

    print(f"\n{'='*60}")
    print(f"  HUELLA DE CARBONO — {VENUE['nombre']}")
    print(f"{'='*60}")
    print(f"  Fichero  : {fichero}")
    print(f"  Columnas detectadas:")
    for k, v in cols.items():
        print(f"    {k:<20} → {v or '(no encontrada)'}")
    print(f"\n  Respuestas registradas: {len(df_raw)}")
    print(f"  (Los orígenes no geocodificables serán excluidos)\n")

    resultados = []
    excluidos  = []

    for idx, fila in df_raw.iterrows():
        fila_id = idx + 1
        col_origen = cols["origen"]
        origen = str(fila[col_origen]).strip() if col_origen else ""

        if origen.lower() in ORIGENES_INVALIDOS or len(origen) < 3:
            excluidos.append({"id": fila_id, "origen": origen})
            print(f"  Omitiendo  #{fila_id:>3} — origen no válido: '{origen}'")
            continue

        print(f"  Procesando #{fila_id:>3} — {origen[:45]}")
        r = procesar_fila(fila, cols, fila_id)
        resultados.append(r)

    df_res = pd.DataFrame(resultados)

    # ── Resumen ───────────────────────────────────────────────────────────────
    total_co2        = df_res["co2_total"].sum()
    total_transp     = df_res["co2_transporte"].sum()
    total_local      = df_res["co2_local"].sum()
    total_aloj       = df_res["co2_alojamiento"].sum()
    media_co2        = total_co2 / len(df_res) if len(df_res) else 0
    n_combinado      = (df_res["transporte_secundario"] != "").sum()
    n_parcial        = (df_res["factor_atribucion"] == 0.5).sum()
    n_no_atrib       = (df_res["factor_atribucion"] == 0.0).sum()
    n_avion          = (df_res["transporte_clave"] == "avion").sum()

    print(f"\n{'='*60}")
    print(f"  RESUMEN TOTAL EVENTO")
    print(f"{'='*60}")
    print(f"  Asistentes incluidos    : {len(resultados):>3}  (excluidos: {len(excluidos)})")
    print(f"  CO₂ total evento        : {total_co2:>10.2f} kg")
    print(f"  CO₂ medio por asistente : {media_co2:>10.2f} kg")
    print(f"    · Transporte          : {total_transp:>10.2f} kg")
    print(f"    · Movilidad local     : {total_local:>10.2f} kg")
    print(f"    · Alojamiento         : {total_aloj:>10.2f} kg")
    print(f"  Viajes combinados       : {n_combinado:>3}")
    print(f"  Viajes parciales (50%)  : {n_parcial:>3}")
    print(f"  Viajes no atribuidos    : {n_no_atrib:>3}")
    print(f"  Viajes en avión         : {n_avion:>3}")

    # Desglose transporte
    print(f"\n{'='*60}")
    print(f"  DESGLOSE POR MEDIO PRINCIPAL")
    print(f"{'='*60}")
    desglose = (
        df_res.groupby("transporte_clave", dropna=False)
        .agg(
            asistentes=("id", "count"),
            co2_kg=("co2_transporte", "sum"),
            distancia_media_km=("distancia_km", "mean"),
        )
        .sort_values("co2_kg", ascending=False)
    )
    for medio, row in desglose.iterrows():
        dm = row["distancia_media_km"]
        dist_str = f"{dm:.1f} km" if dm == dm else "N/A"   # NaN check
        print(f"  {medio:<12} | {int(row['asistentes']):>3} asistentes | "
              f"CO₂: {row['co2_kg']:>8.2f} kg | dist. media: {dist_str}")

    # Detalle
    print(f"\n{'='*60}")
    print(f"  DETALLE POR ASISTENTE")
    print(f"{'='*60}")
    hdr = f"  {'#':>3}  {'Origen':<28}  {'T.Ppal':<10}  {'T.Sec':<8}  {'Oc':>2}  {'Atr':>4}  "
    hdr += f"{'Dist':>7}  {'CO₂tr':>7}  {'CO₂aloj':>7}  {'TOTAL':>8}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in resultados:
        dist_s = f"{r['distancia_km']:.1f}km" if r["distancia_km"] is not None else "  N/A"
        sec_s  = r["transporte_secundario"][:8] if r["transporte_secundario"] else "—"
        print(
            f"  {r['id']:>3}  {r['origen'][:28]:<28}  "
            f"{r['transporte_clave']:<10}  {sec_s:<8}  "
            f"{r['factor_ocupacion']:>2}  {r['factor_atribucion']:>4.1f}  "
            f"{dist_s:>7}  {r['co2_transporte']:>7.3f}  "
            f"{r['co2_alojamiento']:>7.2f}  {r['co2_total']:>8.3f}"
        )

    # Notas
    notas = [(r["id"], r["nota"]) for r in resultados if r["nota"]]
    if notas:
        print(f"\n  NOTAS:")
        for id_, nota in notas:
            print(f"    #{id_:>3}: {nota}")

    # Excluidos
    if excluidos:
        print(f"\n  EXCLUIDOS:")
        for e in excluidos:
            print(f"    #{e['id']:>3}: '{e['origen']}'")

    # ── Informe de anomalías ──────────────────────────────────────────────────
    df_anomalias = df_res[df_res["anomalia_tipo"] != ""].copy() if "anomalia_tipo" in df_res.columns else pd.DataFrame()

    print(f"\n{'='*60}")
    print(f"  INFORME DE ANOMALÍAS DETECTADAS")
    print(f"{'='*60}")
    if df_anomalias.empty:
        print("  ✅  Sin anomalías detectadas.")
    else:
        print(f"  Total de registros con anomalía: {len(df_anomalias)}\n")
        print(f"  {'#':>3}  {'Origen':<28}  {'T.orig':<10}  {'T.final':<10}  {'Dist':>7}  {'Tipo'}")
        print(f"  {'-'*3}  {'-'*28}  {'-'*10}  {'-'*10}  {'-'*7}  {'-'*30}")
        for _, row in df_anomalias.iterrows():
            orig_clave = str(row.get("transporte_original", row.get("transporte_clave", "")))
            dist_s = f"{row['distancia_km']:.1f}km" if pd.notna(row.get("distancia_km")) and row.get("distancia_km") else "  N/A"
            print(
                f"  {int(row['id']):>3}  {str(row['origen'])[:28]:<28}  "
                f"{orig_clave:<10}  {str(row['transporte_clave']):<10}  "
                f"{dist_s:>7}  {row['anomalia_tipo']}"
            )
        # Desglose por tipo
        print(f"\n  Resumen por tipo:")
        for tipo, cnt in df_anomalias["anomalia_tipo"].value_counts().items():
            accion = df_anomalias[df_anomalias["anomalia_tipo"] == tipo]["anomalia_accion"].iloc[0]
            print(f"    {tipo:<30} → {cnt:>2} registro(s)  [{accion}]")

    # Guardar CSV
    out_path = "huella_carbono_resultados.csv"
    df_res.to_csv(out_path, index=False, sep=";")
    print(f"\n  ✅  Resultados guardados en: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
