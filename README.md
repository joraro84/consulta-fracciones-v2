# Consulta de Fracciones - v2 (Turso)

App web de clasificación arancelaria con base de datos persistente en Turso (libSQL).

## Características
- Búsqueda inteligente con normalización (mayúsculas/acentos/espacios)
- Cruce automático BASE × LIGIE × Precios estimados
- 2 perfiles: admin (CRUD completo) y consulta (solo lectura)
- BD persistente: los cambios sobreviven a reinicios

## Tecnología
- Streamlit Cloud (frontend + hosting)
- Turso (libSQL) como base de datos
- HTTP API directo (sin dependencias compiladas)
