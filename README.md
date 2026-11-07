# 🍳 Estandarizador de Recetas en Notion (MCP + Antigravity)

Automatización inteligente para estandarizar recetas en Notion guardadas directamente desde YouTube Shorts, vídeos o páginas web.

El sistema procesa periódicamente tandas de recetas en segundo plano (por defecto 10 por semana), extrayendo ingredientes, instrucciones paso a paso, etiquetas normalizadas, asignando emojis culinarios y embebiendo el vídeo original en la propia página de Notion.

---

## 📌 Flujo de Trabajo

```
[YouTube / Web] (Compartir enlace) 
       │
       ▼
[Notion: Base de Datos "Recetas"] (Registro nuevo: Procesado = Desmarcado)
       │
       ▼
[Antigravity / cron silencioso] (trigger_if_needed.py: 0 tokens si ya se procesó esta semana)
       │
       ▼
[Servidor MCP notion-recetas] (Obtiene lote de 10 recetas sin procesar + metadatos de YouTube)
       │
       ▼
[Agente IA] (Estandariza ingredientes, pasos, formato visual, emojis y etiquetas)
       │
       ▼
[API de Notion] (Actualiza propiedades, bloques de la página y marca Procesado = Marcado)
```

---

## 📋 Requisitos Previos

1. **Python 3.10+** (solo utiliza bibliotecas estándar de Python: `urllib`, `json`, `subprocess`, etc.; no requiere instalar paquetes adicionales con `pip`).
2. **Cuenta de Notion** y un **Token de Integración Interna** (*Internal Integration Token*).
3. **Google Antigravity** (opcional para la automatización desatendida mediante MCP / Sidecars) o ejecución manual por línea de comandos.

---

## 🗄️ Estructura Requerida en Notion

Para que los enlaces se guarden correctamente al pulsar **"Compartir"** desde la aplicación móvil o la extensión web de Notion, y para que el script pueda leerlos y actualizarlos, crea una base de datos en Notion con las siguientes propiedades exactas:

| Nombre de la Propiedad | Tipo en Notion | Descripción |
| :--- | :--- | :--- |
| **`Name`** | `Title` (Título) | Título de la receta. Al compartir desde YouTube suele guardarse automáticamente el título del vídeo. |
| **`Link`** | `URL` | Enlace directo al vídeo de YouTube o receta web. |
| **`Procesado`** | `Checkbox` (Casilla) | Casilla de verificación. Por defecto queda desmarcada (`false`) cuando añades un enlace nuevo. Cuando el script termina de estandarizar la receta, la marca como procesada (`true`). |
| **`Categorías`** | `Multi-select` (Selección múltiple) | Categorías del plato (por ejemplo: `salado`, `dulce`, `comida italiana`, `comida china`, etc.). |
| **`Ingredientes`** | `Multi-select` (Selección múltiple) | Etiquetas normalizadas en minúsculas para filtrar y buscar recetas por ingredientes (por ejemplo: `ajo`, `mantequilla`, `harina de trigo`). |
| **`Fecha de creación`** | `Created time` (Hora de creación) | Fecha automática de creación del registro. Se utiliza para procesar las recetas pendientes por orden cronológico. |

> ⚠️ **Importante**: Conecta tu integración interna de Notion a esta base de datos:
> 1. Abre la base de datos en Notion.
> 2. Haz clic en el menú `•••` (arriba a la derecha) -> **Conexiones** (*Connections*).
> 3. Añade y autoriza tu integración (por ejemplo: `Hermes`).

---

## ⚙️ Instalación y Configuración

### 1. Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/estandarizador-recetas-notion.git
cd estandarizador-recetas-notion
```

### 2. Configurar Variables de Entorno
Copia el archivo de ejemplo `.env.example` a `.env`:
```bash
cp .env.example .env
```
Edita `.env` con tus credenciales:
```env
NOTION_TOKEN=ntn_tu_token_aqui
NOTION_DATABASE_ID=tu_database_id_aqui
```

* **¿Cómo obtener el `NOTION_DATABASE_ID`?**
  Abre tu base de datos de Notion en el navegador web. La URL tiene una estructura similar a:
  `https://www.notion.so/workspace/a1b2c3d4e5f6789012345678abcdef01?v=...`
  La cadena de 32 caracteres hexadecimales situada antes del signo `?` es tu `NOTION_DATABASE_ID`.

---

## 🚀 Modos de Uso

### Opción A: Servidor MCP en Antigravity (Recomendado)
El proyecto incluye un servidor MCP stdio ([notion_recetas_mcp.py](notion_recetas_mcp.py)) que ejecuta las peticiones a la API de Notion y YouTube directamente desde el entorno anfitrión de Antigravity (sin restricciones de sandbox).

1. Añade el servidor a tu archivo `mcp_config.json` (ubicado en `~/.gemini/config/mcp_config.json`):
```json
{
  "mcpServers": {
    "notion-recetas": {
      "command": "python",
      "args": [
        "c:\\ruta\\completa\\al\\proyecto\\notion_recetas_mcp.py"
      ]
    }
  }
}
```

2. Registra la automatización semanal en `~/.gemini/config/sidecars/notion-recetas-semanal/sidecar.json`:
```json
{
  "builtin": "schedule",
  "args": [
    "CRON_TZ=Europe/Madrid 0 * * * *",
    "python",
    "c:\\ruta\\completa\\al\\proyecto\\trigger_if_needed.py"
  ],
  "restart_policy": "always",
  "display_name": "Estandarizar 10 Recetas en Notion (Semanal)",
  "description": "Comprueba silenciosamente cada hora (0 tokens) si la semana actual ya se procesó; activa el agente solo una vez a la semana para estandarizar 10 recetas.",
  "agent_permissions": {
    "workspace_uris": [
      "file:///c:/ruta/completa/al/proyecto"
    ],
    "access_grants": [
      "mcp(notion-recetas/check_weekly_batch)",
      "mcp(notion-recetas/apply_weekly_batch)",
      "read_file(c:/ruta/completa/al/proyecto)",
      "write_file(c:/ruta/completa/al/proyecto)"
    ]
  }
}
```

### Opción B: Ejecución por Línea de Comandos
También puedes consultar y aplicar los cambios manualmente mediante el script CLI:

* **Comprobar si hay registros pendientes:**
  ```bash
  python notion_weekly_batch.py check
  ```
* **Forzar la comprobación ignorando si la semana actual ya se marcó:**
  ```bash
  python notion_weekly_batch.py check --force
  ```
* **Aplicar un lote estandarizado desde un archivo JSON:**
  ```bash
  python notion_weekly_batch.py apply batch_spec.json
  ```
* **Marcar la semana actual como completada manualmente:**
  ```bash
  python notion_weekly_batch.py mark-week
  ```

---

## 📁 Estructura del Proyecto

```text
├── .env.example             # Plantilla de variables de entorno (sin credenciales)
├── .gitignore               # Excluye .env, registros, cachés y estados locales
├── notion_recetas_mcp.py    # Servidor MCP stdio con herramientas check_weekly_batch y apply_weekly_batch
├── notion_weekly_batch.py   # Script CLI para consultar y aplicar tandas de recetas en Notion
├── trigger_if_needed.py     # Guardián de ejecución: 0 tokens si la semana ya fue completada
├── weekly_state.json        # Registro de la última semana ISO procesada (ignorado por Git)
└── README.md                # Documentación del proyecto
```

---

## 🔒 Seguridad
- Nunca subas el archivo `.env` ni claves reales a GitHub.
- El archivo `.gitignore` ya está configurado para evitar publicar credenciales y archivos de estado local.
