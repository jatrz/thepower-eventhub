# thepower-eventhub

Asistente de atención al cliente para un catálogo ficticio de eventos. Responde con las políticas del proyecto y, según la implementación, recuerda la conversación y consulta eventos o pedidos guardados en JSON.

Los datos de `data/` son de práctica. No son pedidos ni clientes reales, y el proyecto no está conectado a una tienda de entradas.

Hay dos implementaciones del mismo ejercicio. No conviven en el mismo árbol de trabajo: cada una está en su rama, para poder ejecutarla sin mezclar módulos ni catálogos.

## Ramas

| Rama | Qué contiene |
|---|---|
| `main` | Configuración común: este README, `.gitignore`, `.env.example` y las dependencias compartidas. |
| `feat/langchain` | Implementación con LangChain y LCEL, por pasos. |
| `feat/langgraph` | Implementación con LangGraph, de un grafo por reglas a un chatbot con herramientas. |

`common.py` no está en `main`. Solo lo usa la rama LangChain, para la memoria de sesión y la cadena LCEL. LangGraph configura el modelo, las políticas y la memoria en `graphs/`.

El catálogo tampoco es común. `data/policies.md` coincide, pero `data/events.json` y `data/orders.json` no. Por eso cada rama lleva sus propios datos.

## Requisitos

- Python 3.
- `venv`.
- Una clave válida en `OPENAI_API_KEY` para las versiones que llaman al modelo. La V1 de LangGraph no la necesita.
- PostgreSQL accesible, solo para `graphs/v3_postgres.py` en `feat/langgraph`.

## Instalación

Desde la raíz de esta carpeta:

```bash
python -m venv .venv
```

En Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

En Ubuntu o WSL:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` y no lo subas. Está en `.gitignore`.

`requirements.txt` de `main` fija lo que comparten las dos implementaciones. La rama `feat/langgraph` añade `langgraph` y los paquetes del checkpointer de PostgreSQL.

## Variables

| Variable | Dónde se usa | Qué poner |
|---|---|---|
| `OPENAI_API_KEY` | LangChain y LangGraph, salvo la V1 | Clave de la API. El programa no debe imprimirla. |
| `OPENAI_MODEL` | Las mismas versiones | Identificador de modelo aceptado por esa API. |
| `POSTGRES_URI` | Solo `graphs/v3_postgres.py` | URI de PostgreSQL. El programa no debe imprimirla. |

Si se quita `OPENAI_MODEL`, la rama LangChain usa el modelo por defecto de `ChatOpenAI`. La rama LangGraph no elige otro modelo si este falla.

## Cómo pasar a una implementación

```bash
git checkout feat/langchain
git checkout feat/langgraph
```

El README de cada rama describe su estructura, cómo ejecutarla y qué pruebas tiene. Este archivo no las mezcla.

Para volver a la base:

```bash
git checkout main
```
