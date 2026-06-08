"""
CONSULTA DE FRACCIONES - v2 (Turso BD persistente)
"""
import streamlit as st
import pandas as pd
import database as db
import io
from datetime import datetime

st.set_page_config(
    page_title="Consulta de Fracciones",
    page_icon="🔎",
    layout="wide"
)


@st.cache_resource
def _init():
    db.init_db()
    return True

try:
    _init()
except Exception as e:
    st.error(f"❌ Error conectando a Turso: {e}")
    st.stop()


def login():
    st.title("🔎 CONSULTA DE FRACCIONES")
    st.subheader("Inicio de sesión")
    pwd = st.text_input("Contraseña", type="password", key="pwd_login")
    if st.button("Entrar", type="primary", use_container_width=True):
        admin_pwd = st.secrets.get("passwords", {}).get("admin", "admin2026")
        cons_pwd = st.secrets.get("passwords", {}).get("consulta", "agencia2026")
        if pwd == admin_pwd:
            st.session_state["modo"] = "admin"
            st.rerun()
        elif pwd == cons_pwd:
            st.session_state["modo"] = "consulta"
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.caption("Hay dos accesos: administrador (puede modificar) y consulta (solo búsqueda).")


def mostrar_resultados(resultados):
    if not resultados:
        st.info("Sin resultados.")
        return
    st.success(f"**{len(resultados)} resultados encontrados**")
    data = []
    for r in resultados:
        id_, desc, desc_fac, frac, ar, umt, pre, obs = r
        arancel_fmt = f"{int(ar*100)}%" if ar is not None else ""
        precio_fmt = f"{pre:.2f}" if pre is not None else ""
        data.append({
            "DESCRIPCION": desc or "",
            "DESCRIPCION FACTURA": desc_fac or "",
            "FRACCION": frac or "",
            "ARANCEL": arancel_fmt,
            "UMT": umt or "",
            "PRECIO ESTIMADO": precio_fmt,
            "OBSERVACIONES": obs or "",
        })
    df = pd.DataFrame(data)

    def estilo_precio(val):
        if val and str(val).strip() != "":
            return "background-color: #991B1B; color: white; font-weight: 600;"
        return ""

    def estilo_zebra(row):
        idx = row.name
        return ['background-color: #F4F7FA' if idx % 2 == 0 else 'background-color: #FFFFFF' for _ in row]

    sty = df.style.apply(estilo_zebra, axis=1).map(estilo_precio, subset=['PRECIO ESTIMADO'])
    st.dataframe(sty, use_container_width=True, hide_index=False)


def modo_consulta():
    st.title("🔎 CONSULTA DE FRACCIONES")
    n_base, n_ar, n_est = db.contar_registros()
    st.caption(f"📦 {n_base} productos · 📋 {n_ar} fracciones LIGIE · 💲 {n_est} precios estimados")
    criterio = st.text_input("Escribe una palabra (mayúsculas/acentos no importan)", key="busq_cons")
    if criterio:
        resultados = db.buscar(criterio)
        mostrar_resultados(resultados)
    with st.sidebar:
        if st.button("Cerrar sesión"):
            del st.session_state["modo"]
            st.rerun()


def modo_admin():
    st.title("🔎 CONSULTA DE FRACCIONES - Administrador")
    n_base, n_ar, n_est = db.contar_registros()
    st.caption(f"📦 {n_base} productos · 📋 {n_ar} fracciones LIGIE · 💲 {n_est} precios estimados")

    with st.sidebar:
        st.success("Modo: ADMINISTRADOR")
        if st.button("Cerrar sesión"):
            del st.session_state["modo"]
            st.rerun()

    tabs = st.tabs([
        "🔎 Consultar",
        "➕ Agregar / Editar",
        "📦 Subir BASE (Excel)",
        "📤 Subir LIGIE (Excel)",
        "💲 Subir Precios (Excel)",
        "💾 Descargar Backup"
    ])

    with tabs[0]:
        criterio = st.text_input("Escribe una palabra", key="busq_admin")
        if criterio:
            mostrar_resultados(db.buscar(criterio))

    with tabs[1]:
        st.markdown("### Agregar nuevo producto o editar existente")
        criterio_e = st.text_input("Busca el producto que quieres editar (deja vacío para agregar nuevo)", key="busq_edit")
        seleccionado = None
        if criterio_e:
            res = db.buscar(criterio_e, limite=20)
            if res:
                opciones = ["(Nuevo producto)"] + [f"{r[0]} - {r[1]} ({r[3] or 'sin frac'})" for r in res]
                sel = st.selectbox("Selecciona uno:", opciones, key="sel_edit")
                if sel != "(Nuevo producto)":
                    sel_id = int(sel.split(" - ")[0])
                    seleccionado = db.obtener_registro(sel_id)

        if seleccionado:
            id_e, d_e, df_e, fr_e, pm_e, obs_e = seleccionado
            st.info(f"Editando ID {id_e}")
        else:
            id_e = None
            d_e, df_e, fr_e, pm_e, obs_e = "", "", "", None, ""

        col1, col2 = st.columns(2)
        with col1:
            d = st.text_input("DESCRIPCION", value=d_e, key="form_d")
            fr = st.text_input("FRACCION (10 dígitos)", value=fr_e or "", key="form_f")
            pm = st.text_input("PRECIO ESTIMADO (manual, opcional)", value=str(pm_e) if pm_e is not None else "", key="form_p")
        with col2:
            df_ = st.text_input("DESCRIPCION FACTURA", value=df_e, key="form_df")
            obs = st.text_input("OBSERVACIONES", value=obs_e or "", key="form_obs")

        c1, c2, c3 = st.columns([1, 1, 4])
        with c1:
            if st.button("💾 Guardar", type="primary"):
                if not d.strip():
                    st.error("La DESCRIPCION es obligatoria")
                else:
                    pm_val = pm.strip() if pm else None
                    try:
                        if id_e:
                            db.actualizar_registro(id_e, d, df_, fr, obs, pm_val)
                            st.success("✅ Actualizado")
                        else:
                            db.agregar_registro(d, df_, fr, obs, pm_val)
                            st.success("✅ Agregado")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Error: {ex}")
        with c2:
            if id_e:
                if st.button("🗑️ Eliminar"):
                    db.eliminar_registro(id_e)
                    st.success("✅ Eliminado")
                    st.rerun()

    with tabs[2]:
        st.markdown("### 📦 Reemplazar BASE de productos completa")
        st.warning("⚠️ Esto BORRA todos los productos actuales y los reemplaza por los del Excel que subas.")
        st.caption("Formato: pestaña BASE con columnas DESCRIPCION, DESCRIPCION FACTURA, FRACCION, [...], OBSERVACIONES.")
        uploaded = st.file_uploader("Sube Excel con la BASE", type=["xlsx", "xlsm"], key="up_base")
        if uploaded:
            try:
                df = pd.read_excel(uploaded, sheet_name='BASE', engine='openpyxl')
                df = df.dropna(subset=[df.columns[0]])
                st.info(f"Detectados {len(df)} productos en el archivo.")
                if st.button("⚠️ REEMPLAZAR BASE AHORA", type="primary"):
                    with st.spinner("Subiendo a Turso..."):
                        n = db.reemplazar_base(df)
                    st.success(f"✅ {n} productos cargados en Turso")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error: {ex}")

    with tabs[3]:
        st.markdown("### 📤 Reemplazar LIGIE (ARANCELES)")
        st.warning("⚠️ Esto BORRA toda la LIGIE actual.")
        st.caption("Formato: pestaña ARANCELES con columnas FRACCION, ARANCEL (decimal: 0.15 = 15%), UMT.")
        upl = st.file_uploader("Sube Excel LIGIE", type=["xlsx", "xlsm"], key="up_ligie")
        if upl:
            try:
                df_ar = pd.read_excel(upl, sheet_name='ARANCELES', engine='openpyxl')
                st.info(f"Detectadas {len(df_ar)} fracciones en el archivo.")
                if st.button("⚠️ REEMPLAZAR LIGIE AHORA", type="primary"):
                    with st.spinner("Subiendo a Turso..."):
                        n = db.reemplazar_aranceles(df_ar)
                    st.success(f"✅ {n} fracciones LIGIE cargadas")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error: {ex}")

    with tabs[4]:
        st.markdown("### 💲 Reemplazar Precios Estimados")
        st.warning("⚠️ Esto BORRA todos los precios estimados actuales.")
        st.caption("Formato: pestaña 'estimado' con columnas FRACCION, DESCRIPCION NICO, UMT, PRECIO ESTIMADO.")
        upe = st.file_uploader("Sube Excel de Precios Estimados", type=["xlsx", "xlsm"], key="up_est")
        if upe:
            try:
                df_e = pd.read_excel(upe, sheet_name='estimado', engine='openpyxl')
                st.info(f"Detectados {len(df_e)} precios en el archivo.")
                if st.button("⚠️ REEMPLAZAR PRECIOS AHORA", type="primary"):
                    with st.spinner("Subiendo a Turso..."):
                        n = db.reemplazar_estimado(df_e)
                    st.success(f"✅ {n} precios cargados")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error: {ex}")

    with tabs[5]:
        st.markdown("### 💾 Descargar respaldo completo")
        st.caption("Genera un Excel con TODAS las tablas (BASE, ARANCELES, estimado) de la BD actual.")
        if st.button("📥 Generar Excel de respaldo"):
            with st.spinner("Generando..."):
                buf = io.BytesIO()
                db.exportar_excel(buf)
                buf.seek(0)
            fecha = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                "⬇️ Descargar Excel",
                data=buf.getvalue(),
                file_name=f"respaldo_consulta_{fecha}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


if "modo" not in st.session_state:
    login()
elif st.session_state["modo"] == "admin":
    modo_admin()
else:
    modo_consulta()
