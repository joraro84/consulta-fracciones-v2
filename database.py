"""
Base de datos para CONSULTA DE FRACCIONES v2 - Turso vía HTTP API
"""
import requests
import pandas as pd
import streamlit as st


def _get_creds():
    base_url = st.secrets["turso"]["url"].replace("libsql://", "https://")
    token = st.secrets["turso"]["token"]
    return base_url, token


def _to_arg(value):
    """Convierte valor Python a formato Turso hrana v2.
    IMPORTANTE: float debe enviarse como número, no string."""
    if value is None:
        return {"type": "null"}
    # Detectar NaN/NaT
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
        return {"type": "float", "value": float(value)}  # ¡NÚMERO, no string!
    # numpy types
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


def _post_pipeline(stmts):
    s, base_url = _session()
    reqs = []
    for st_item in stmts:
        if isinstance(st_item, tuple):
            sql, args = st_item
            reqs.append({"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(a) for a in args]}})
        else:
            reqs.append({"type": "execute", "stmt": {"sql": st_item}})
    reqs.append({"type": "close"})
    r = s.post(f"{base_url}/v2/pipeline", json={"requests": reqs}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Turso HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    for res in data.get("results", []):
        if res.get("type") == "error":
            err = res.get("error", {})
            raise RuntimeError(f"Turso SQL error: {err.get('message', str(err))[:300]}")
    return data


def _query(sql, args=None):
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
    if not r.ok:
        raise RuntimeError(f"Turso HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    res = data["results"][0]
    if res.get("type") == "error":
        raise RuntimeError(f"Turso SQL: {res.get('error',{}).get('message', '')[:300]}")
    result = res["response"]["result"]
    rows = []
    for row in result.get("rows", []):
        rows.append(tuple(_arg_to_py(c) for c in row))
    return rows


def _execute(sql, args=None):
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
    if not r.ok:
        raise RuntimeError(f"Turso HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    res = data["results"][0]
    if res.get("type") == "error":
        raise RuntimeError(f"Turso SQL: {res.get('error',{}).get('message', '')[:300]}")
    return res["response"]["result"]


def normalizar(texto):
    if texto is None:
        return ""
    try:
        if pd.isna(texto):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(texto).upper().strip()
    rep = {'Á':'A','É':'E','Í':'I','Ó':'O','Ú':'U','Ü':'U','Ñ':'N',
           'á':'A','é':'E','í':'I','ó':'O','ú':'U','ü':'U','ñ':'N'}
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


SCHEMA_VERSION = "v2"


def init_db():
    _post_pipeline([
        "CREATE TABLE IF NOT EXISTS metadata (clave TEXT PRIMARY KEY, valor TEXT)"
    ])
    try:
        rows = _query("SELECT valor FROM metadata WHERE clave = ?", ["schema_version"])
        current = rows[0][0] if rows else None
    except Exception:
        current = None
    if current == SCHEMA_VERSION:
        return
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
    rid = res.get("last_insert_rowid")
    return int(rid) if rid else 0


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


BATCH_SIZE = 100


def _bulk_insert(sql_template, rows):
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
                if not pd.isna(row.iloc[5]):
                    try:
                        v = row.iloc[5]
                        pm = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
                    except (ValueError, TypeError):
                        pm = None
                obs = str(row.iloc[6]) if not pd.isna(row.iloc[6]) else ""
            elif len(row) >= 4:
                obs = str(row.iloc[3]) if not pd.isna(row.iloc[3]) else ""
            rows.append([desc, desc_fac, fraccion, pm, obs, normalizar(desc)])
        except Exception:
            continue
    return _bulk_insert(
        "INSERT INTO base (descripcion, descripcion_factura, fraccion, precio_manual, observaciones, desc_norm) VALUES (?,?,?,?,?,?)",
        rows
    )


def reemplazar_aranceles(df):
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
