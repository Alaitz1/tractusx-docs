# Tractus-X Docs Index — README

Pequeña app Flask que **indexa** la documentación de los repos de una organización de GitHub y la muestra en un **árbol navegable** con visor Markdown (incluye Mermaid).  
En el primer uso, es posible que tengas que entrar en **`/admin`** y poner tu **token personal de GitHub** para que la app pueda llamar a la API sin límites.

---

## Requisitos

- Python 3.10+  
- Acceso HTTP saliente (para llamar a `api.github.com` y `raw.githubusercontent.com`)
- (Recomendado) **Token personal de GitHub** con permisos **solo lectura pública**  
  - *Scopes sugeridos:* `public_repo` (o **ningún scope** si solo usas repos públicos)

---

## Variables de entorno (opcional)

| Variable              | Valor por defecto          | Descripción |
|----------------------|----------------------------|-------------|
| `OUT`                | `tractusx-docs`            | Carpeta donde se generan `index.html`, `viewer.html` y `tree.json`. |
| `ORG`                | `eclipse-tractusx`         | Organización de GitHub a indexar. |
| `PATHS`              | `docs,documentation,doc,website/docs` | Rutas “raíz” que se consideran documentación dentro de cada repo. |
| `MONTHS_BACK`        | `6`                        | Solo indexa repos con actividad (push) en los últimos N meses. Usa `0` para desactivar filtro. |
| `FAST_MODE`          | `1`                        | Modo rápido de indexado (sí). |
| `WORKERS`            | `12`                       | Paralelismo para llamadas a GitHub en modo rápido. |
| `GITHUB_TOKEN`       | *(vacío)*                  | Token por defecto del servidor para la API. Se puede sobreescribir desde `/admin`. |
| `ADMIN_SECRET`       | *(vacío)*                  | Si lo defines, protege `/run` y pide este secreto en `/admin`. |
| `ADMIN_FIRST`        | `0`                        | Si `1`, al entrar en `/` se redirige primero a `/admin`. |
| `PORT`               | `5000`                     | Puerto HTTP. |

---

## Puesta en marcha

```bash

# ) Instalar dependencias
pip install flask

# 2) Exportar variables (ejemplos)
export ORG="eclipse-tractusx"
export MONTHS_BACK=6
export PATHS="docs,documentation,doc,website/docs"
# (opcional) forzar que primero se abra /admin
export ADMIN_FIRST=1

# 3) Lanzar
python3 app.py
```

Abre el navegador en: **http://localhost:5000/**

---

## Primer uso: entrar en `/admin` y añadir token (recomendado)

La API de GitHub **limita** fuertemente las llamadas anónimas. Para evitar errores 403/limit o tiempos de espera:

1. Entra en **`/admin`** (la app redirige automáticamente si es la primera vez o si `ADMIN_FIRST=1`).  
2. Pega tu **token personal** (no se guarda en disco; se usa solo para esa ejecución manual).  
3. Pulsa **“Ejecutar ahora”** para generar el índice.  
4. Abre el **índice** (botón o ruta `/`).

> Puedes ajustar `MONTHS_BACK` si no ves algunos repos (p. ej., `MONTHS_BACK=0` para no filtrar por fecha) y volver a **Ejecutar ahora**.

---



## Problemas comunes

- **Veo “Sin archivos…” o no aparecen repos**  
  - Aumenta `MONTHS_BACK` (o `0` para desactivar) y vuelve a ejecutar `/admin`.
  - Asegúrate de que `PATHS` cubre las carpetas reales (p. ej. `docs`).
  - Mira `tree.json` en `OUT/` para confirmar qué se generó.

- **Rate limit / 403**  
  - Usa un **token personal** en `/admin` o exporta `GITHUB_TOKEN`.

---

## Seguridad

- El token introducido en `/admin` **no se persiste**.  
- Si necesitas proteger `/run`, define `ADMIN_SECRET`.  
- Para despliegue público, pon la app detrás de un proxy con autenticación (p. ej., ingress con auth).

---

## Ejemplos rápidos

**Indexar toda la org sin límite por fecha:**
```bash
export ORG="mi-organizacion"
export MONTHS_BACK=0
python app.py
# Navega a /admin → Ejecutar ahora con tu token
```

**Cambiar rutas de documentación:**
```bash
export PATHS="docs,documentation,handbook,guide"
python app.py
```

---


