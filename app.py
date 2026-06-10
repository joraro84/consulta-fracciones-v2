"""
CONSULTA DE FRACCIONES - v2 (Turso BD persistente)
"""
import streamlit as st
import pandas as pd
import database as db
import io
import html as html_lib
from datetime import datetime

st.set_page_config(
    page_title="Consulta de Fracciones",
    page_icon="🔎",
    layout="wide"
)

HIDE_STREAMLIT = """
<style>
header[data-testid="stHeader"] {display: none !important; visibility: hidden !important; height: 0 !important;}
[data-testid="stToolbar"] {display: none !important;}
.stDeployButton, [data-testid="stDeployButton"], [data-testid="stAppDeployButton"] {display: none !important;}
#MainMenu, .stApp [data-testid="stStatusWidget"] {display: none !important;}
[data-testid="stMainMenu"], [data-testid="stHeaderActionElements"] {display: none !important;}
.stApp > header, .stApp {margin-top: 0 !important;}
.stApp h1 a, .stApp h2 a, .stApp h3 a {display: none !important;}
footer {display: none !important; visibility: hidden !important;}
.viewerBadge_container__1QSob, [class*="viewerBadge"], div[class*="viewerBadge"], a[class*="viewerBadge"] {display: none !important;}
.viewerBadge_link__qRIco, .viewerBadge_text__1JaDK {display: none !important;}
[data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stConnectionStatus"] {display: none !important;}
.stStatusWidget, ._terminalButton, ._profileContainer {display: none !important;}
[class*="_link_"], [class*="_container_"][class*="viewer"] {display: none !important;}
a[href*="streamlit.io"], a[href*="github.com"], a[href*="share.streamlit"], a[href*="streamlit.app"] {display: none !important;}
section[data-testid="stSidebar"] {display: none !important; width: 0 !important;}
[data-testid="collapsedControl"], button[kind="header"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}
.stApp > div:first-child > div:first-child {margin-left: 0 !important;}
.stTextInput > div > div, .stPasswordInput > div > div, [data-baseweb="input"], [data-baseweb="base-input"] {
    border: 1.5px solid #4B5563 !important;
    border-radius: 6px !important;
}
.stTextInput input, .stPasswordInput input, [data-baseweb="input"] input {
    background-color: #FFFFFF !important;
    color: #1F2937 !important;
}
.stTextInput > div > div:focus-within, .stPasswordInput > div > div:focus-within, [data-baseweb="input"]:focus-within {
    border: 2px solid #1F2937 !important;
    box-shadow: 0 0 0 1px #1F2937 !important;
}
</style>
"""
st.markdown(HIDE_STREAMLIT, unsafe_allow_html=True)


@st.cache_resource
def _init():
    db.init_db()
    return True

try:
    _init()
except Exception as e:
    st.error(f"❌ Error conectando a Turso: {e}")
    st.stop()


def header_con_salir(titulo):
    col_t, col_s = st.columns([8, 1])
    with col_t:
        st.title(titulo)
    with col_s:
        st.write("")
        if st.button("🚪 Salir", key=f"logout_{titulo[:10]}", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


def login():
    st.title("🔎 CONSULTA DE FRACCIONES")
    st.subheader("Inicio de sesión")
    pwd = st.text_input("Contraseña", type="password", key="pwd_login")
    if st.button("Entrar", type="primary", use_container_width=True):
        admin_pwd = db.obtener_password("admin") or st.secrets.get("passwords", {}).get("admin", "admin2026")
        cons_pwd = db.obtener_password("consulta") or st.secrets.get("passwords", {}).get("consulta", "agencia2026")
        if pwd == admin_pwd:
            st.session_state["modo"] = "admin"
            st.rerun()
        elif pwd == cons_pwd:
            st.session_state["modo"] = "consulta"
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.caption("Hay dos accesos: administrador (puede modificar) y consulta (solo búsqueda).")


def _esc(v):
    return html_lib.escape(str(v)) if v is not None else ""


def mostrar_resultados(resultados):
    if not resultados:
        st.info("Sin resultados.")
        return
    st.success(f"**{len(resultados)} resultados encontrados**")
    css = """
    <style>
    .tabla-wrapper { overflow-x: auto; margin-top: 8px; border-radius: 6px; }
    table.tabla-resultados {
        width: 100%; border-collapse: collapse;
        font-family: 'Source Sans Pro', sans-serif; font-size: 14px; color: #1F2937;
    }
    table.tabla-resultados thead th {
        background-color: #F3F4F6; color: #374151; padding: 10px 12px;
        text-align: center; font-weight: 600;
        border-bottom: 2px solid #D1D5DB; white-space: nowrap;
    }
    table.tabla-resultados thead th.col-factura {
        background-color: #87CEEB; color: #0F172A; font-weight: 700;
    }
    table.tabla-resultados tbody td {
        padding: 8px 12px; border-bottom: 1px solid #E5E7EB;
        vertical-align: top; text-align: left;
    }
    table.tabla-resultados tbody td.center { text-align: center; }
    table.tabla-resultados tbody td.nowrap { white-space: nowrap; }
    table.tabla-resultados tbody tr.par td { background-color: #E0EBF5; }
    table.tabla-resultados tbody tr.impar td { background-color: #FFFFFF; }
    table.tabla-resultados td.precio-est {
        background-color: #991B1B !important; color: #FFFFFF;
        font-weight: 600; text-align: center;
    }
    </style>
    """
    filas_html = ""
    for idx, r in enumerate(resultados):
        id_, desc, desc_fac, frac, ar, umt, pre, obs = r
        arancel_fmt = f"{int(ar*100)}%" if ar is not None else ""
        precio_fmt = f"{pre:.2f}" if pre is not None else ""
        clase = "par" if idx % 2 == 0 else "impar"
        precio_class = "precio-est" if precio_fmt else "center"
        filas_html += (
            f"<tr class='{clase}'>"
            f"<td>{_esc(desc)}</td>"
            f"<td class='nowrap'>{_esc(desc_fac)}</td>"
            f"<td class='center'>{_esc(frac)}</td>"
            f"<td class='center'>{_esc(arancel_fmt)}</td>"
            f"<td class='center'>{_esc(umt)}</td>"
            f"<td class='{precio_class}'>{_esc(precio_fmt)}</td>"
            f"<td>{_esc(obs)}</td>"
            f"</tr>"
        )
    tabla_html = (
        css +
        "<div class='tabla-wrapper'>"
        "<table class='tabla-resultados'>"
        "<thead><tr>"
        "<th>DESCRIPCION</th>"
        "<th class='col-factura'>DESCRIPCION FACTURA</th>"
        "<th>FRACCION</th><th>ARANCEL</th><th>UMT</th><th>PRECIO ESTIMADO</th><th>OBSERVACIONES</th>"
        "</tr></thead><tbody>"
        + filas_html +
        "</tbody></table></div>"
    )
    st.markdown(tabla_html, unsafe_allow_html=True)


def modo_consulta():
    header_con_salir("🔎 CONSULTA DE FRACCIONES")
    n_base, n_ar, n_est = db.contar_registros()
    st.caption(f"📦 {n_base} productos · 📋 {n_ar} fracciones LIGIE · 💲 {n_est} precios estimados")
    criterio = st.text_input("Escribe una palabra (mayúsculas/acentos no importan)", key="busq_cons")
    if criterio:
        resultados = db.buscar(criterio)
        mostrar_resultados(resultados)


def modo_admin():
    header_con_salir("🔎 CONSULTA DE FRACCIONES - Administrador")
    n_base, n_ar, n_est = db.contar_registros()
    st.caption(f"📦 {n_base} productos · 📋 {n_ar} fracciones LIGIE · 💲 {n_est} precios estimados · Modo: ADMINISTRADOR")

    tabs = st.tabs([
        "🔎 Consultar",
        "➕ Agregar / Editar",
        "📦 Subir BASE (Excel)",
        "📤 Subir LIGIE (Excel)",
        "💲 Subir Precios (Excel)",
        "💾 Descargar Backup",
        "🔑 Contraseñas"
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

        sel_id_actual = seleccionado[0] if seleccionado else None
        sel_id_anterior = st.session_state.get("edit_sel_id_actual")
        if sel_id_actual != sel_id_anterior:
            st.session_state["edit_sel_id_actual"] = sel_id_actual
            if seleccionado:
                _, d_v, df_v, fr_v, pm_v, obs_v = seleccionado
                st.session_state["form_d"] = d_v or ""
                st.session_state["form_df"] = df_v or ""
                st.session_state["form_f"] = fr_v or ""
                st.session_state["form_p"] = str(pm_v) if pm_v is not None else ""
                st.session_state["form_obs"] = obs_v or ""
            else:
                st.session_state["form_d"] = ""
                st.session_state["form_df"] = ""
                st.session_state["form_f"] = ""
                st.session_state["form_p"] = ""
                st.session_state["form_obs"] = ""
            st.rerun()

        if seleccionado:
            st.info(f"✏️ Editando ID {seleccionado[0]} - los campos están pre-llenados con los datos actuales")
            id_e = seleccionado[0]
        else:
            id_e = None
            if criterio_e:
                st.caption("Llena los datos para AGREGAR un nuevo producto.")

        col1, col2 = st.columns(2)
        with col1:
            d = st.text_input("DESCRIPCION", key="form_d")
            fr = st.text_input("FRACCION (10 dígitos)", key="form_f")
            pm = st.text_input("PRECIO ESTIMADO (manual, opcional)", key="form_p")
        with col2:
            df_ = st.text_input("DESCRIPCION FACTURA", key="form_df")
            obs = st.text_input("OBSERVACIONES", key="form_obs")

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
                            st.success(f"✅ Registro ID {id_e} actualizado")
                        else:
                            new_id = db.agregar_registro(d, df_, fr, obs, pm_val)
                            st.success(f"✅ Nuevo producto agregado (ID {new_id})")
                        for k in ["form_d", "form_df", "form_f", "form_p", "form_obs", "edit_sel_id_actual"]:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Error: {ex}")
        with c2:
            if id_e:
                if st.button("🗑️ Eliminar"):
                    db.eliminar_registro(id_e)
                    for k in ["form_d", "form_df", "form_f", "form_p", "form_obs", "edit_sel_id_actual"]:
                        if k in st.session_state:
                            del st.session_state[k]
                    st.success(f"✅ Registro ID {id_e} eliminado")
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

    with tabs[6]:
        st.markdown("### 🔑 Cambiar contraseñas de acceso")
        st.caption("Aquí actualizas la contraseña de cada perfil. El cambio aplica al instante.")

        st.markdown("#### Perfil ADMINISTRADOR")
        st.caption("Solo tú. Si la cambias, escribe la nueva en un lugar seguro porque NO se muestra después.")
        with st.form("form_pass_admin", clear_on_submit=True):
            new_admin = st.text_input("Nueva contraseña admin", type="password", key="new_pass_admin")
            if st.form_submit_button("💾 Actualizar contraseña ADMIN", type="primary"):
                if not new_admin or not new_admin.strip():
                    st.error("Escribe una contraseña válida")
                else:
                    try:
                        db.cambiar_password("admin", new_admin.strip())
                        st.success("✅ Contraseña ADMIN actualizada")
                    except Exception as ex:
                        st.error(f"Error: {ex}")

        st.divider()

        st.markdown("#### Perfil CONSULTA (los 20 usuarios)")
        st.caption("Cuando cambies esta contraseña, avísales a tus 20 usuarios la nueva.")
        with st.form("form_pass_consulta", clear_on_submit=True):
            new_cons = st.text_input("Nueva contraseña consulta", type="password", key="new_pass_cons")
            if st.form_submit_button("💾 Actualizar contraseña CONSULTA", type="primary"):
                if not new_cons or not new_cons.strip():
                    st.error("Escribe una contraseña válida")
                else:
                    try:
                        db.cambiar_password("consulta", new_cons.strip())
                        st.success("✅ Contraseña CONSULTA actualizada")
                    except Exception as ex:
                        st.error(f"Error: {ex}")


if "modo" not in st.session_state:
    login()
elif st.session_state["modo"] == "admin":
    modo_admin()
else:
    modo_consulta()
