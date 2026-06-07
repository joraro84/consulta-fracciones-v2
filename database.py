"""
Base de datos para CONSULTA DE FRACCIONES v2.
Usa Turso (libSQL) vía HTTP API directo con requests.
BD persistente, sin dependencias compiladas.
"""
import requests
import pandas as pd
import streamlit as st


def _get_creds():
    base_url = st.secrets["turso"]["url"].replace("libsql://", "https://")
    token = st.secrets["turso"]["token"]
    return base_url, token


def _to_arg(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": str(value)}
    return {"type": "text", "value": str(value)}


def _arg_to_py(arg):
    t = arg.get("type")
    if t == "null":
        return None
    v = arg.get("value")
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    return v


@st.cache_resource
def _session():
    s = requests.Session()
    base_url, token = _get_creds()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s, base_url


def _post_pipeline(stmts):
    """stmts: lista de (sql, args) o sql string. Ejecuta en una sola request HTTP."""
    s, base_url = _session()
    reqs = []
    for st_item in stmts:
        if isinstance(st_item, tuple):
            sql, args = st_item
            reqs.append({"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(a) for a in args]}})
        else:
            reqs.append({"type": "execute", "stmt": {"sql": st_item}})
    reqs.append({"type": "close"})
    r = s.post(f"{base_url}/v2/pipeline", json={"requests": reqs}, timeout=60)
    r.raise_for_status()
    return r.json()


def _query(sql, args=None):
    """Ejecuta SELECT y devuelve lista de tuplas."""
    args = args or []
    s, base_url = _session()
    r = s.post(
        f"{base_url}/v2/pipeline",
        json={"requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(a) for a in args]}},
            {"type": "close"}
        ]},
        timeout=60
    )
    r.raise_for_status()
    data = r.json()
    res = data["results"][0]
    if res.get("type") != "ok":
        raise RuntimeError(f"Query error: {res}")
    result = res["response"]["result"]
    rows = []
    for row in result.get("rows", []):
        rows.append(tuple(_arg_to_py(c) for c in row))
    return rows


def _execute(sql, args=None):
    """Ejecuta INSERT/UPDATE/DELETE simple."""
    args = args or []
    s, base_url = _session()
    r = s.post(
        f"{base_url}/v2/pipeline",
        json={"requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(a) for a in args]}},
            {"type": "close"}
        ]},
        timeout=60
    )
    r.raise_for_status()
    data = r.json()
    res = data["results"][0]
    if res.get("type") != "ok":
        raise RuntimeError(f"Execute error: {res}")
    return res["response"]["result"]


# === Normalización ===
def normalizar(texto):
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = str(texto).upper().strip()
    rep = {'Á':'A','É':'E','Í':'I','Ó':'O','Ú':'U','Ü':'U','Ñ':'N',
           'á':'A','é':'E','í':'I','ó':'O','ú':'U','ü':'U','ñ':'N'}
    for o, n in rep.items():
        s = s.replace(o, n)
    while '  ' in s:
        s = s.replace('  ', ' ')
    return s


def normalizar_fraccion(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
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


# === Esquema ===
SCHEMA_VERSION = "v2"


def init_db():
    """Crea las tablas. Si BD tiene versión diferente, limpia y recrea."""
    # 1) Crear metadata primero (si no existe)
    _post_pipeline([
        "CREATE TABLE IF NOT EXISTS metadata (clave TEXT PRIMARY KEY, valor TEXT)"
    ])
    # 2) Verificar versión actual
    try:
        rows = _query("SELECT valor FROM metadata WHERE clave = ?", ["schema_version"])
        current = rows[0][0] if rows else None
    except Exception:
        current = None

    if current == SCHEMA_VERSION:
        return  # ya está al día

    # 3) Limpiar todo y crear esquema fresco
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


# === Búsqueda ===
def buscar(criterio, limite=100):
    if not criterio or not criterio.strip():
        return []
    cn = normalizar(criterio)
    if not cn:
        return []
    return _query("""
        SELECT b.id, b.descripcion, b.descripcion_factura, b.fraccion,
               a.arancel, a.umt,
               COALESCE(b.precio_manual, e.precio) AS precio_final,
               b.observaciones
        FROM base b
        LEFT JOIN aranceles a ON a.fraccion = b.fraccion
        LEFT JOIN estimado e ON e.fraccion = b.fraccion
        WHERE b.desc_norm LIKE ?
        LIMIT ?
    """, [f'%{cn}%', limite])


def contar_registros():
    n_base = _query("SELECT COUNT(*) FROM base")[0][0]
    n_ar = _query("SELECT COUNT(*) FROM aranceles")[0][0]
    n_est = _query("SELECT COUNT(*) FROM estimado")[0][0]
    return n_base, n_ar, n_est


def obtener_registro(id_reg):
    rows = _query(
        "SELECT id, descripcion, descripcion_factura, fraccion, precio_manual, observaciones FROM base WHERE id = ?",
        [id_reg]
    )
    return rows[0] if rows else None


# === CRUD individuales ===
def agregar_registro(descripcion, desc_factura, fraccion, observaciones="", precio_manual=None):
    fn = normalizar_fraccion(fraccion)
    pm = None
    if precio_manual is not None and str(precio_manual).strip() != "":
        try:
            pm = float(precio_manual)
        except (ValueError, TypeError):
            pm = None
    res = _execute(
        "INSERT INTO base (descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm) VALUES (?,?,?,?,?,?)",
        [descripcion, desc_factura, fn, pm, observaciones, normalizar(descripcion)]
    )
    return int(res.get("last_insert_rowid", "0"))


def actualizar_registro(id_reg, descripcion, desc_factura, fraccion, observaciones, precio_manual=None):
    fn = normalizar_fraccion(fraccion)
    pm = None
    if precio_manual is not None and str(precio_manual).strip() != "":
        try:
            pm = float(precio_manual)
        except (ValueError, TypeError):
            pm = None
    _execute(
        "UPDATE base SET descripcion=?, descripcion_factura=?, fraccion=?, precio_manual=?, observaciones=?, desc_norm=? WHERE id=?",
        [descripcion, desc_factura, fn, pm, observaciones, normalizar(descripcion), id_reg]
    )


def eliminar_registro(id_reg):
    _execute("DELETE FROM base WHERE id=?", [id_reg])


# === Bulk upload desde Excel (en batches HTTP) ===
BATCH_SIZE = 250  # statements por request HTTP


def _bulk_insert(sql_template, rows):
    """Ejecuta muchos INSERTs en lotes de BATCH_SIZE statements por request HTTP."""
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i+BATCH_SIZE]
        stmts = [(sql_template, row) for row in chunk]
        _post_pipeline(stmts)
        total += len(chunk)
    return total


def reemplazar_base(df):
    """Reemplaza tabla BASE completa desde DataFrame."""
    _execute("DELETE FROM base", [])
    rows = []
    for _, row in df.iterrows():
        try:
            desc = str(row.iloc[0]) if not pd.isna(row.iloc[0]) else ""
            if not desc.strip():
                continue
            desc_fac = str(row.iloc[1]) if len(row) > 1 and not pd.isna(row.iloc[1]) else ""
            fraccion = normalizar_fraccion(row.iloc[2]) if len(row) > 2 else ""
            pm = None
            obs = ""
            if len(row) >= 7:
                # Excel completo (A=desc,B=desc_fac,C=frac,D=arancel,E=umt,F=precio,G=obs)
                if not pd.isna(row.iloc[5]):
                    try:
                        v = row.iloc[5]
                        pm = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
                    except (ValueError, TypeError):
                        pm = None
                obs = str(row.iloc[6]) if not pd.isna(row.iloc[6]) else ""
            elif len(row) >= 4:
                # Machote simple (A=desc,B=desc_fac,C=frac,D=obs)
                obs = str(row.iloc[3]) if not pd.isna(row.iloc[3]) else ""
            rows.append([desc, desc_fac, fraccion, pm, obs, normalizar(desc)])
        except Exception:
            continue
    return _bulk_insert(
        "INSERT INTO base (descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm) VALUES (?,?,?,?,?,?)",
        rows
    )


def reemplazar_aranceles(df):
    """Reemplaza tabla ARANCELES desde DataFrame (3 columnas: FRACCION, ARANCEL, UMT)."""
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
    return _bulk_insert("INSERT INTO aranceles (fraccion, arancel, umt) VALUES (?,?,?)", rows)


def reemplazar_estimado(df):
    """Reemplaza tabla estimado desde DataFrame (4 columnas)."""
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
    return _bulk_insert("INSERT INTO estimado (fraccion, descripcion_nico, umt, precio) VALUES (?,?,?,?)", rows)


# === Export ===
def exportar_excel(ruta_salida):
    base_rows = _query("SELECT descripcion, descripcion_factura, fraccion, precio_manual, observaciones FROM base")
    df_base = pd.DataFrame(base_rows, columns=['DESCRIPCION', 'DESCRIPCION FACTURA', 'FRACCION', 'PRECIO ESTIMADO', 'OBSERVACIONES'])
    ar_rows = _query("SELECT fraccion, arancel, umt FROM aranceles")
    df_ar = pd.DataFrame(ar_rows, columns=['FRACCION', 'ARANCEL', 'UMT'])
    est_rows = _query("SELECT fraccion, descripcion_nico, umt, precio FROM estimado")
    df_est = pd.DataFrame(est_rows, columns=['FRACCION', 'DESCRIPCION NICO', 'UMT', 'PRECIO ESTIMADO'])
    with pd.ExcelWriter(ruta_salida, engine='openpyxl') as writer:
        df_base.to_excel(writer, sheet_name='BASE', index=False)
        df_ar.to_excel(writer, sheet_name='ARANCELES', index=False)
        df_est.to_excel(writer, sheet_name='estimado', index=False)
