"""
Base de datos para CONSULTA DE FRACCIONES v3 - Turso vía HTTP API
ARQUITECTURA EN MEMORIA:
  - Al arrancar, la app carga las 3 tablas y las contraseñas desde Turso UNA sola vez.
  - Todas las búsquedas y consultas se hacen sobre la copia en memoria (instantáneas,
    no dependen de que Turso responda).
  - Turso solo se usa para GUARDAR cambios del admin y para la carga inicial.
  - Toda llamada a Turso tiene reintentos automáticos si el servidor está saturado
    ("Server database capacity temporarily exceeded").
"""
import time
import requests
import pandas as pd
import streamlit as st

# ==========================================================================
# CONEXIÓN A TURSO (con reintentos automáticos)
# ==========================================================================

_REINTENTOS = 4          # intentos totales por llamada
_ESPERA_BASE = 2         # segundos; crece en cada reintento (2, 4, 6...)

_MENSAJES_TEMPORALES = (
    "capacity", "temporarily", "try again", "timeout", "timed out",
    "busy", "overloaded", "connection", "reset", "unavailable",
)


def _es_error_temporal(msg):
    m = str(msg).lower()
    return any(p in m for p in _MENSAJES_TEMPORALES)


def _get_creds():
    base_url = st.secrets["turso"]["url"].replace("libsql://", "https://")
    token = st.secrets["turso"]["token"]
    return base_url, token


def _to_arg(value):
    if value is None:
        return {"type": "null"}
    try:
        if pd.isna(value):
            return {"type": "null"}
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": float(value)}
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return {"type": "integer", "value": str(int(value))}
        if isinstance(value, np.floating):
            return {"type": "float", "value": float(value)}
    except ImportError:
        pass
    return {"type": "text", "value": str(value)}


def _arg_to_py(arg):
    t = arg.get("type")
    if t == "null":
        return None
    v = arg.get("value")
    if t == "integer":
        return int(v) if v is not None else None
    if t == "float":
        return float(v) if v is not None else None
    return v


@st.cache_resource
def _session():
    s = requests.Session()
    base_url, token = _get_creds()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s, base_url


def _armar_requests(stmts):
    reqs = []
    for st_item in stmts:
        if isinstance(st_item, tuple):
            sql, args = st_item
            reqs.append({"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(a) for a in args]}})
        else:
            reqs.append({"type": "execute", "stmt": {"sql": st_item}})
    reqs.append({"type": "close"})
    return reqs


def _post_pipeline(stmts, timeout=120):
    """Ejecuta una lista de sentencias en Turso. Reintenta automáticamente
    si el error es temporal (saturación del servidor, red, timeout)."""
    s, base_url = _session()
    reqs = _armar_requests(stmts)
    ultimo_error = None
    for intento in range(_REINTENTOS):
        try:
            r = s.post(f"{base_url}/v2/pipeline", json={"requests": reqs}, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Turso HTTP {r.status_code}: {r.text[:300]}")
            if not r.ok:
                # Error NO temporal (token inválido, petición mal formada): no reintentar
                raise RuntimeError(f"Turso HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            for res in data.get("results", []):
                if res.get("type") == "error":
                    err = res.get("error", {})
                    raise RuntimeError(f"Turso SQL: {err.get('message', str(err))[:300]}")
            return data
        except (requests.RequestException, RuntimeError) as e:
            ultimo_error = e
            temporal = isinstance(e, requests.RequestException) or _es_error_temporal(e)
            if temporal and intento < _REINTENTOS - 1:
                time.sleep(_ESPERA_BASE * (intento + 1))
                continue
            raise
    raise ultimo_error


def _extraer_filas(res):
    result = res["response"]["result"]
    filas = []
    for row in result.get("rows", []):
        filas.append(tuple(_arg_to_py(c) for c in row))
    return filas


def _query(sql, args=None, timeout=120):
    data = _post_pipeline([(sql, args or [])], timeout=timeout)
    return _extraer_filas(data["results"][0])


def _query_multi(sqls, timeout=120):
    """Varias consultas SELECT en UNA sola llamada HTTP. Regresa lista de listas de filas."""
    data = _post_pipeline([(sql, []) for sql in sqls], timeout=timeout)
    return [_extraer_filas(res) for res in data["results"][:len(sqls)]]


def _execute(sql, args=None, timeout=120):
    data = _post_pipeline([(sql, args or [])], timeout=timeout)
    return data["results"][0]["response"]["result"]


# ==========================================================================
# NORMALIZACIÓN (idéntica a la versión anterior)
# ==========================================================================

def normalizar(texto):
    if texto is None:
        return ""
    try:
        if pd.isna(texto):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(texto).upper().strip()
    rep = {'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ü': 'U', 'Ñ': 'N',
           'á': 'A', 'é': 'E', 'í': 'I', 'ó': 'O', 'ú': 'U', 'ü': 'U', 'ñ': 'N'}
    for o, n in rep.items():
        s = s.replace(o, n)
    while '  ' in s:
        s = s.replace('  ', ' ')
    return s


def normalizar_fraccion(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        if isinstance(valor, (int, float)):
            return f"{int(valor):010d}"
        s = str(valor).strip().replace(' ', '')
        if '.' in s:
            s = s.split('.')[0]
        if not s.isdigit():
            return ""
        return f"{int(s):010d}"
    except (ValueError, TypeError):
        return ""


# ==========================================================================
# ALMACÉN EN MEMORIA (una sola copia compartida por todos los usuarios)
# ==========================================================================

@st.cache_resource(show_spinner="Cargando base de datos...")
def _datos():
    """Carga TODO desde Turso una sola vez y lo mantiene en memoria.
    Si la carga falla, no se guarda nada en caché y el siguiente intento recarga."""
    store = {
        "base": [],        # lista de dicts: id, descripcion, descripcion_factura,
                           #                 fraccion, precio_manual, observaciones, desc_norm
        "aranceles": {},   # fraccion -> (arancel, umt)
        "estimado": {},    # fraccion -> (descripcion_nico, umt, precio)
        "passwords": {},   # 'admin' / 'consulta' -> contraseña
    }
    filas_meta, filas_base, filas_ar, filas_est = _query_multi([
        "SELECT clave, valor FROM metadata",
        "SELECT id, descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm FROM base",
        "SELECT fraccion, arancel, umt FROM aranceles",
        "SELECT fraccion, descripcion_nico, umt, precio FROM estimado",
    ])
    for clave, valor in filas_meta:
        if clave == "pass_admin":
            store["passwords"]["admin"] = valor
        elif clave == "pass_consulta":
            store["passwords"]["consulta"] = valor
    for f in filas_base:
        store["base"].append({
            "id": f[0], "descripcion": f[1], "descripcion_factura": f[2],
            "fraccion": f[3], "precio_manual": f[4], "observaciones": f[5],
            "desc_norm": f[6] if f[6] is not None else normalizar(f[1]),
        })
    for fraccion, arancel, umt in filas_ar:
        store["aranceles"][fraccion] = (arancel, umt)
    for fraccion, desc_nico, umt, precio in filas_est:
        store["estimado"][fraccion] = (desc_nico, umt, precio)
    return store


def recargar_datos():
    """Descarta la copia en memoria y la vuelve a cargar desde Turso."""
    _datos.clear()
    return _datos()


def _recargar_base_en_memoria():
    """Recarga SOLO la tabla base desde Turso hacia la memoria (para obtener los IDs
    después de una carga masiva)."""
    store = _datos()
    filas = _query("SELECT id, descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm FROM base")
    nueva = []
    for f in filas:
        nueva.append({
            "id": f[0], "descripcion": f[1], "descripcion_factura": f[2],
            "fraccion": f[3], "precio_manual": f[4], "observaciones": f[5],
            "desc_norm": f[6] if f[6] is not None else normalizar(f[1]),
        })
    store["base"][:] = nueva


# ==========================================================================
# INICIALIZACIÓN DEL ESQUEMA
# ==========================================================================

SCHEMA_VERSION = "v2"


def init_db():
    _post_pipeline([
        "CREATE TABLE IF NOT EXISTS metadata (clave TEXT PRIMARY KEY, valor TEXT)"
    ])
    # IMPORTANTE: si esta lectura falla, se lanza el error tal cual.
    # NUNCA asumir que no hay versión (eso antes podía borrar las tablas con datos).
    rows = _query("SELECT valor FROM metadata WHERE clave = ?", ["schema_version"])
    current = rows[0][0] if rows else None
    if current != SCHEMA_VERSION:
        if current is None:
            # Base nueva de verdad: crear esquema desde cero
            _post_pipeline([
                "DROP TABLE IF EXISTS base",
                "DROP TABLE IF EXISTS aranceles",
                "DROP TABLE IF EXISTS estimado",
                """CREATE TABLE base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    descripcion TEXT,
                    descripcion_factura TEXT,
                    fraccion TEXT,
                    precio_manual REAL,
                    observaciones TEXT,
                    desc_norm TEXT
                )""",
                "CREATE INDEX idx_desc_norm ON base(desc_norm)",
                "CREATE INDEX idx_fraccion ON base(fraccion)",
                "CREATE TABLE aranceles (fraccion TEXT PRIMARY KEY, arancel REAL, umt TEXT)",
                "CREATE TABLE estimado (fraccion TEXT PRIMARY KEY, descripcion_nico TEXT, umt TEXT, precio REAL)",
                ("INSERT OR REPLACE INTO metadata (clave, valor) VALUES (?, ?)", ["schema_version", SCHEMA_VERSION]),
            ])
        else:
            raise RuntimeError(
                f"La base tiene esquema '{current}' y la app espera '{SCHEMA_VERSION}'. "
                "Por seguridad NO se borran las tablas automáticamente."
            )
    # Cargar la copia en memoria (con reintentos incluidos)
    _datos()


# ==========================================================================
# CONSULTAS (100% en memoria — no tocan Turso)
# ==========================================================================

def contar_registros():
    store = _datos()
    return len(store["base"]), len(store["aranceles"]), len(store["estimado"])


def obtener_registro(id_reg):
    store = _datos()
    for r in store["base"]:
        if r["id"] == id_reg:
            return (r["id"], r["descripcion"], r["descripcion_factura"],
                    r["fraccion"], r["precio_manual"], r["observaciones"])
    return None


def _fila_resultado(r, store):
    ar_umt = store["aranceles"].get(r["fraccion"])
    arancel = ar_umt[0] if ar_umt else None
    umt = ar_umt[1] if ar_umt else None
    if r["precio_manual"] is not None:
        precio_final = r["precio_manual"]
    else:
        est = store["estimado"].get(r["fraccion"])
        precio_final = est[2] if est else None
    return (r["id"], r["descripcion"], r["descripcion_factura"], r["fraccion"],
            arancel, umt, precio_final, r["observaciones"])


def buscar(criterio, limite=100):
    """Detecta automáticamente fracción (solo dígitos) o descripción.
    Busca en la copia en memoria: instantáneo y no depende de Turso."""
    if not criterio or not criterio.strip():
        return []
    store = _datos()
    limpio = criterio.strip()
    for ch in [' ', '.', '-']:
        limpio = limpio.replace(ch, '')
    resultados = []
    if limpio.isdigit():
        prefijo = limpio[:10]
        for r in store["base"]:
            if r["fraccion"] and r["fraccion"].startswith(prefijo):
                resultados.append(_fila_resultado(r, store))
                if len(resultados) >= limite:
                    break
        return resultados
    cn = normalizar(criterio)
    if not cn:
        return []
    for r in store["base"]:
        if cn in r["desc_norm"]:
            resultados.append(_fila_resultado(r, store))
            if len(resultados) >= limite:
                break
    return resultados


# ==========================================================================
# ESCRITURAS (van a Turso con reintentos Y actualizan la memoria)
# ==========================================================================

def _limpiar_precio(precio_manual):
    if precio_manual is not None and str(precio_manual).strip() != "":
        try:
            return float(precio_manual)
        except (ValueError, TypeError):
            return None
    return None


def agregar_registro(descripcion, desc_factura, fraccion, observaciones="", precio_manual=None):
    store = _datos()
    fn = normalizar_fraccion(fraccion)
    pm = _limpiar_precio(precio_manual)
    res = _execute(
        "INSERT INTO base (descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm) VALUES (?,?,?,?,?,?)",
        [descripcion, desc_factura, fn, pm, observaciones, normalizar(descripcion)]
    )
    rid = res.get("last_insert_rowid")
    rid = int(rid) if rid else 0
    store["base"].append({
        "id": rid, "descripcion": descripcion, "descripcion_factura": desc_factura,
        "fraccion": fn, "precio_manual": pm, "observaciones": observaciones,
        "desc_norm": normalizar(descripcion),
    })
    return rid


def actualizar_registro(id_reg, descripcion, desc_factura, fraccion, observaciones, precio_manual=None):
    store = _datos()
    fn = normalizar_fraccion(fraccion)
    pm = _limpiar_precio(precio_manual)
    _execute(
        "UPDATE base SET descripcion=?, descripcion_factura=?, fraccion=?, precio_manual=?, observaciones=?, desc_norm=? WHERE id=?",
        [descripcion, desc_factura, fn, pm, observaciones, normalizar(descripcion), id_reg]
    )
    for r in store["base"]:
        if r["id"] == id_reg:
            r["descripcion"] = descripcion
            r["descripcion_factura"] = desc_factura
            r["fraccion"] = fn
            r["precio_manual"] = pm
            r["observaciones"] = observaciones
            r["desc_norm"] = normalizar(descripcion)
            break


def eliminar_registro(id_reg):
    store = _datos()
    _execute("DELETE FROM base WHERE id=?", [id_reg])
    store["base"][:] = [r for r in store["base"] if r["id"] != id_reg]


BATCH_SIZE = 100


def _bulk_insert(sql_template, rows):
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        stmts = [(sql_template, row) for row in chunk]
        _post_pipeline(stmts)
        total += len(chunk)
    return total


def reemplazar_base(df):
    """Lee columnas por NOMBRE (acepta backup de 5 cols o formato original de 7)."""
    _execute("DELETE FROM base", [])
    cols = {}
    for i, c in enumerate(df.columns):
        cols[normalizar(str(c))] = i
    idx_desc = cols.get("DESCRIPCION", 0)
    idx_fac = cols.get("DESCRIPCION FACTURA", 1)
    idx_frac = cols.get("FRACCION", 2)
    idx_pm = cols.get("PRECIO ESTIMADO")
    idx_obs = cols.get("OBSERVACIONES")
    rows = []
    for _, row in df.iterrows():
        try:
            desc = str(row.iloc[idx_desc]) if not pd.isna(row.iloc[idx_desc]) else ""
            if not desc.strip():
                continue
            desc_fac = str(row.iloc[idx_fac]) if not pd.isna(row.iloc[idx_fac]) else ""
            fraccion = normalizar_fraccion(row.iloc[idx_frac])
            pm = None
            if idx_pm is not None and not pd.isna(row.iloc[idx_pm]):
                try:
                    v = row.iloc[idx_pm]
                    pm = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
                except (ValueError, TypeError):
                    pm = None
            obs = ""
            if idx_obs is not None and not pd.isna(row.iloc[idx_obs]):
                obs = str(row.iloc[idx_obs])
            rows.append([desc, desc_fac, fraccion, pm, obs, normalizar(desc)])
        except Exception:
            continue
    total = _bulk_insert(
        "INSERT INTO base (descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm) VALUES (?,?,?,?,?,?)",
        rows
    )
    _recargar_base_en_memoria()
    return total


def reemplazar_aranceles(df):
    store = _datos()
    _execute("DELETE FROM aranceles", [])
    rows = []
    seen = set()
    for _, row in df.iterrows():
        try:
            fraccion = normalizar_fraccion(row.iloc[0])
            if not fraccion or fraccion in seen:
                continue
            seen.add(fraccion)
            arancel = float(row.iloc[1]) if not pd.isna(row.iloc[1]) else None
            umt = str(row.iloc[2]) if not pd.isna(row.iloc[2]) else ""
            rows.append([fraccion, arancel, umt])
        except Exception:
            continue
    # INSERT OR REPLACE: si un lote se reintenta por saturación, no genera duplicados
    total = _bulk_insert("INSERT OR REPLACE INTO aranceles (fraccion, arancel, umt) VALUES (?,?,?)", rows)
    store["aranceles"].clear()
    for fraccion, arancel, umt in rows:
        store["aranceles"][fraccion] = (arancel, umt)
    return total


def reemplazar_estimado(df):
    store = _datos()
    _execute("DELETE FROM estimado", [])
    rows = []
    seen = set()
    for _, row in df.iterrows():
        try:
            fraccion = normalizar_fraccion(row.iloc[0])
            if not fraccion or fraccion in seen:
                continue
            seen.add(fraccion)
            desc_nico = str(row.iloc[1]) if not pd.isna(row.iloc[1]) else ""
            umt = str(row.iloc[2]) if not pd.isna(row.iloc[2]) else ""
            precio = float(row.iloc[3]) if not pd.isna(row.iloc[3]) else None
            rows.append([fraccion, desc_nico, umt, precio])
        except Exception:
            continue
    total = _bulk_insert("INSERT OR REPLACE INTO estimado (fraccion, descripcion_nico, umt, precio) VALUES (?,?,?,?)", rows)
    store["estimado"].clear()
    for fraccion, desc_nico, umt, precio in rows:
        store["estimado"][fraccion] = (desc_nico, umt, precio)
    return total


# ==========================================================================
# RESPALDO (100% desde memoria — no depende de Turso)
# ==========================================================================

def exportar_excel(ruta_salida):
    store = _datos()
    df_base = pd.DataFrame(
        [(r["descripcion"], r["descripcion_factura"], r["fraccion"], r["precio_manual"], r["observaciones"])
         for r in store["base"]],
        columns=['DESCRIPCION', 'DESCRIPCION FACTURA', 'FRACCION', 'PRECIO ESTIMADO', 'OBSERVACIONES'])
    df_ar = pd.DataFrame(
        [(f, v[0], v[1]) for f, v in store["aranceles"].items()],
        columns=['FRACCION', 'ARANCEL', 'UMT'])
    df_est = pd.DataFrame(
        [(f, v[0], v[1], v[2]) for f, v in store["estimado"].items()],
        columns=['FRACCION', 'DESCRIPCION NICO', 'UMT', 'PRECIO ESTIMADO'])
    with pd.ExcelWriter(ruta_salida, engine='openpyxl') as writer:
        df_base.to_excel(writer, sheet_name='BASE', index=False)
        df_ar.to_excel(writer, sheet_name='ARANCELES', index=False)
        df_est.to_excel(writer, sheet_name='estimado', index=False)


# ==========================================================================
# CONTRASEÑAS (se leen de memoria; se cambian en Turso + memoria)
# ==========================================================================

def obtener_password(perfil):
    """Lee la contraseña del perfil ('admin' o 'consulta') desde la memoria.
    Si no existe, la inicializa con el valor de Streamlit Secrets y la guarda en Turso."""
    store = _datos()
    if perfil in store["passwords"] and store["passwords"][perfil]:
        return store["passwords"][perfil]
    default = st.secrets.get("passwords", {}).get(perfil, "")
    if default:
        _execute("INSERT OR REPLACE INTO metadata (clave, valor) VALUES (?, ?)", [f"pass_{perfil}", default])
        store["passwords"][perfil] = default
    return default


def cambiar_password(perfil, nuevo_valor):
    """Actualiza la contraseña del perfil ('admin' o 'consulta') en Turso y en memoria."""
    store = _datos()
    _execute("INSERT OR REPLACE INTO metadata (clave, valor) VALUES (?, ?)", [f"pass_{perfil}", nuevo_valor])
    store["passwords"][perfil] = nuevo_valor
