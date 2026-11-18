# thepower-eventhub — LangGraph

Implementación LangGraph del repositorio unificado `thepower-eventhub`. La rama de esta entrega es `feat/langfuse_y_smith`. No es `feat/langs` ni `feat/langgraph`: parte del trabajo de LangGraph y añade Langfuse y LangSmith. La configuración común (`.gitignore` y `.env.example`) está en `main`. La otra implementación está en `feat/langchain`.

## Entrega

Lo que se entrega es la rama completa `feat/langfuse_y_smith` y el informe [evidencias/langfuseysmith_ENTREGABLE.pdf](evidencias/langfuseysmith_ENTREGABLE.pdf). El PDF resume Langfuse y LangSmith. El código, las pruebas, las capturas de `evidencias/` y este README están en esa misma rama.

Asistente de práctica para consultar eventos, pedidos y políticas de EventHub. El proyecto reconstruye ese asistente con LangGraph, de un grafo por reglas hasta un chatbot con modelo de lenguaje, memoria y herramientas.

No está conectado a una plataforma real de venta de entradas. Los eventos, pedidos y políticas son datos locales de demostración. PostgreSQL, cuando se usa, solo persiste el estado de la conversación de LangGraph.

## Objetivo de la actividad

Reconstruir de forma progresiva un asistente virtual EventHub:

1. Clasificar intenciones con reglas y enrutar el grafo.
2. Sustituir el estado propio por un historial de mensajes y un modelo de lenguaje.
3. Conservar la conversación por `thread_id`, primero en memoria y después en PostgreSQL.
4. Dejar que el modelo consulte herramientas reales antes de responder.

Cada versión es un módulo independiente. No hay una aplicación única que las ejecute a la vez.

## Arquitectura

| Componente | Qué hace en este proyecto |
|---|---|
| Estado | V1 usa un `TypedDict` con `mensaje`, `intencion` y `respuesta`. A partir de V2 el estado es `MessagesState`. |
| Nodos | Funciones de Python registradas en un `StateGraph`. V1 clasifica y responde con textos fijos. V2, V3 y V4 comparten un nodo `chatbot`. V4 añade el nodo `herramientas`. |
| Grafos | Cada versión compila su propio grafo. El flujo condicional está en el código, no en un orquestador externo. |
| Modelo | `ChatOpenAI`, configurado con `OPENAI_API_KEY` y `OPENAI_MODEL`. V1 no llama a ningún modelo. |
| Herramientas | Solo V4. Usa `buscar_eventos` y `consultar_pedido` de `tools/` y las ejecuta con `ToolNode`. |
| Datos | `data/events.json`, `data/orders.json` y `data/policies.md`. Las políticas entran en el prompt desde V2. Los JSON los leen las herramientas de V4. |
| Checkpointers | V3 usa `InMemorySaver`. La variante PostgreSQL usa `PostgresSaver`. V1, V2 y V4 no tienen checkpointer. |

```mermaid
flowchart TD
    usuario[Terminal]
    env[".env"]
    datos["data/events.json\ndata/orders.json\ndata/policies.md"]
    v1["V1\nreglas y rutas condicionales"]
    v2["V2\nMessagesState y ChatOpenAI"]
    v3["V3\nInMemorySaver"]
    v3pg["V3 PostgreSQL\nPostgresSaver"]
    v4["V4\nToolNode"]
    modelo["API del modelo\nOPENAI_MODEL"]
    postgres[("PostgreSQL\nPOSTGRES_URI")]
    herramientas["buscar_eventos\nconsultar_pedido"]

    usuario --> v1
    usuario --> v2
    usuario --> v3
    usuario --> v3pg
    usuario --> v4
    env --> v2
    env --> v3
    env --> v3pg
    env --> v4
    datos --> v2
    datos --> v3
    datos --> v3pg
    v2 --> modelo
    v3 --> modelo
    v3pg --> modelo
    v4 --> modelo
    v3pg --> postgres
    v4 --> herramientas
    herramientas --> datos
```

## Evolución del proyecto

### V1: grafo simple

`graphs/v1_simple.py` no usa modelo ni API. El estado es un `TypedDict`. El nodo `clasificar` detecta `eventos`, `pedido`, `politicas` u `otro` con reglas. `add_conditional_edges` envía el flujo a `responder_eventos`, `responder_pedido` o `responder_general`, y de ahí a `END`. `politicas` y `otro` comparten el nodo general.

### V2: chatbot

`graphs/v2_chatbot.py` sustituye el estado por `MessagesState`. El nodo `chatbot` lee `data/policies.md`, construye un prompt de sistema en español y llama a `ChatOpenAI`. El grafo es `START` → `chatbot` → `END`. El bucle de terminal conserva el historial pasando los mensajes anteriores en cada invocación. No hay checkpointer. Termina con `salir` o `exit`.

### V3: memoria en el proceso

`graphs/v3_memory.py` reutiliza el nodo, el prompt y el modelo de V2, y compila el grafo con `InMemorySaver`. Cada conversación usa su `thread_id` (`conversacion_1` y `conversacion_2`). Las llamadas del mismo hilo reenvían solo el mensaje nuevo; el checkpointer recupera el resto. `graph.get_state(config)` lee el historial. Esa memoria desaparece al cerrar el proceso.

### V4: herramientas

`graphs/v4_tools.py` registra `buscar_eventos` y `consultar_pedido` en el modelo y las ejecuta con `ToolNode`. Si el último `AIMessage` trae `tool_calls`, el flujo va a `herramientas` y vuelve a `chatbot`. Si no hay llamadas, termina. `consultar_pedido` exige identificador y email coincidente. `buscar_eventos` filtra por ciudad y categoría. El límite de 12 pasos se aplica con `recursion_limit` al hacer `graph.stream()`; no es un nodo del grafo. Si se supera, se captura `GraphRecursionError` y se muestra un mensaje de parada.

Las herramientas están en `tools/` de esta rama. Leen `data/events.json` y `data/orders.json` locales. `buscar_eventos` incluye el `id` del evento en el resultado, para que el modelo pueda cruzarlo con los identificadores que devuelve el pedido. No hace falta el repositorio hermano de LangChain.

## Extra: PostgreSQL

`graphs/v3_postgres.py` es una variante de V3. No modifica el grafo de memoria en RAM y no usa `InMemorySaver`.

`PostgresSaver.from_conn_string(POSTGRES_URI)` abre la conexión durante el modo elegido y la cierra al terminar. `checkpointer.setup()` crea las tablas del checkpointer. Los dos modos usan el hilo `eventhub_postgres_demo` y no borran el historial.

| | `InMemorySaver` | `PostgresSaver` |
|---|---|---|
| Dónde vive el historial | En el proceso de Python | En PostgreSQL |
| Tras cerrar el programa | Se pierde | Se puede recuperar con el mismo `thread_id` |
| Módulo | `graphs/v3_memory.py` | `graphs/v3_postgres.py` |

PostgreSQL no sustituye a `orders.json` ni a `events.json`. Solo guarda checkpoints de LangGraph.

## Estructura de carpetas

```text
.
├── data/
│   ├── events.json
│   ├── orders.json
│   └── policies.md
├── diagrams/
│   ├── v1_graph.mmd
│   └── v4_graph.mmd
├── evidencias/
│   ├── v1_diagrama.png
│   ├── v1_pruebas.png
│   ├── v2_conversacion.png
│   ├── v3_memoria.png
│   ├── v3_postgres_guardar.png
│   ├── v3_postgres_recuperar.png
│   ├── v4_conversacion.png
│   └── v4_diagrama.png
├── graphs/
│   ├── v1_simple.py
│   ├── v2_chatbot.py
│   ├── v3_memory.py
│   ├── v3_postgres.py
│   └── v4_tools.py
├── tests/
│   └── test_v1_simple.py
├── tools/
│   ├── events_tool.py
│   └── orders_tool.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

- `data/`: catálogo, pedidos y políticas ficticias. No los genera el código.
- `diagrams/`: diagramas Mermaid de V1 y V4.
- `evidencias/`: capturas de las pruebas y el informe `langfuseysmith_ENTREGABLE.pdf`.
- `graphs/`: una versión por archivo. No hay un grafo que las combine.
- `tests/`: cuatro pruebas de unittest para las intenciones de V1. No hay pruebas automáticas de V2, V3 ni V4.
- `tools/`: `buscar_eventos` y `consultar_pedido`. No incluye la reserva de entradas.
- `.env`: configuración local. No debe publicarse. No está en el ejemplo de arriba porque `.gitignore` lo excluye.

## Requisitos previos

- WSL2 con Ubuntu.
- Python 3. La revisión de este entorno se hizo con Python 3.14.4. No se han probado otras versiones.
- `venv`, incluido en la instalación habitual de Python.
- Git, para cambiar a la rama de la entrega (`git checkout feat/langfuse_y_smith`).
- Una clave y un identificador de modelo aceptados por la API configurada en `OPENAI_MODEL`. V1 no los necesita.
- PostgreSQL accesible desde Ubuntu, solo para `graphs/v3_postgres.py`.

## Instalación

Desde la raíz del proyecto, en la terminal de Ubuntu:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` de esta rama ya declara `langgraph`, `langgraph-checkpoint-postgres` y `psycopg`. `psycopg-pool` se instala como dependencia de `langgraph-checkpoint-postgres`. No hace falta un `pip install` aparte.

## Dependencias

`requirements.txt` fija:

- `langchain==1.4.9`
- `langchain-openai==1.7.4`
- `openai==3.46.0`
- `python-dotenv==1.2.4`
- `langgraph==1.2.22`
- `langgraph-checkpoint-postgres==3.2.1`
- `psycopg==3.3.9`
- `langfuse==5.2.0`
- `langsmith==0.14.17`

## Configuración

Copia la plantilla y edítala. No subas el archivo real.

```bash
cp .env.example .env
```

Variables que lee el código:

| Variable | Dónde se usa | Qué poner |
|---|---|---|
| `OPENAI_API_KEY` | V2, V3, V4 y V3 PostgreSQL | Clave de la API. El programa no la imprime. |
| `OPENAI_MODEL` | Las mismas versiones | Identificador de modelo que acepte esa API. El código no elige otro si este falla. |
| `POSTGRES_URI` | Solo `graphs/v3_postgres.py` | URI de PostgreSQL. El programa no la imprime. |
| `LANGFUSE_PUBLIC_KEY` | `observability/langfuse_tracing.py` y `observability/prompts.py` | Clave pública. El programa no la imprime. |
| `LANGFUSE_SECRET_KEY` | Los mismos módulos | Clave secreta. El programa no la imprime. |
| `LANGFUSE_BASE_URL` | Los mismos módulos | `https://cloud.langfuse.com` si no se define otra. |
| `LANGSMITH_TRACING` | SDK de LangSmith, leído al ejecutar el grafo | `true` para trazar. No hace falta un callback en V4. |
| `LANGSMITH_API_KEY` | El mismo SDK | Clave de LangSmith. El programa no la imprime. |
| `LANGSMITH_PROJECT` | El mismo SDK | Proyecto de trazas. En esta práctica, `thepower-eventhub`. |
| `LANGSMITH_ENDPOINT` | El mismo SDK | Solo si la cuenta no es la de Estados Unidos. La europea es `https://eu.api.smith.langchain.com`. |

V1 no lee `.env`.

Ejemplo ficticio, no válido para conectar:

```text
OPENAI_API_KEY=pon_aqui_tu_api_key
OPENAI_MODEL=gpt-6-luna
POSTGRES_URI=postgresql://usuario:contrasena@localhost:5432/eventhub
```

Para PostgreSQL, la base debe existir y el usuario de la URI debe poder crear las tablas del checkpointer. El programa llama a `checkpointer.setup()`, pero no crea la base de datos.

## Ejecución

Activa antes el entorno:

```bash
source .venv/bin/activate
```

Todos los comandos se lanzan desde la raíz del proyecto.

### V1

```bash
python -m graphs.v1_simple
python -m unittest tests.test_v1_simple -v
```

El primer comando imprime cuatro casos y regenera `diagrams/v1_graph.mmd`.

### V2

```bash
python -m graphs.v2_chatbot
```

Escribe mensajes y termina con `salir` o `exit`.

### V3 en memoria

```bash
python -m graphs.v3_memory
```

Ejecuta sola la demostración de `conversacion_1` y `conversacion_2`.

### V4

```bash
python -m graphs.v4_tools
```

Usa `tools/events_tool.py` y `tools/orders_tool.py` de esta rama. No necesita Langfuse.

### V4 con trazas de Langfuse

```bash
python -m observability.langfuse_tracing
```

Hace falta un `.env` con claves reales de OpenAI y de Langfuse. Si faltan, el comando termina con código 2 y no llama al modelo. La API usada es la de Langfuse 5: `langfuse.langchain.CallbackHandler` y `propagate_attributes`. No se usa el cliente antiguo `trace()` / `span()`.

Cada una de las 10 consultas usa un `session_id` propio (`s6-traza-01` a `s6-traza-10`) y el `user_id` fijo `usuario-demo-eventhub`. Ese identificador no es un correo. V4 no tiene checkpointer, así que el `thread_id` no conserva mensajes entre consultas; solo identifica la sesión de la traza.

La pregunta enviada al modelo puede incluir un correo ficticio de `data/orders.json`, porque `consultar_pedido` lo exige. No se usa como `user_id`. La salida local lo oculta. La traza remota recibe la pregunta original.

Este comando no lee tokens, costes ni duraciones. Esos datos solo aparecen en Langfuse si el proveedor los envía. La captura de la interfaz está en `evidencias/s6_langfuse_traza.png`.

El comando anterior ya no construye el prompt de sistema en local. Descarga `eventhub-sistema` con la etiqueta `production`, sustituye `marca` y `tono`, y enlaza esa versión en la traza. Si el prompt no está publicado, termina sin llamar al modelo.

`graphs/v4_tools.py` sigue compilando su prompt local. Así la demostración de V4 no depende de Langfuse ni importa el SDK. La lógica de nodos y herramientas no cambia.

### Prompt gestionado

Langfuse 5.2.0 expone `create_prompt` y `get_prompt`. El nombre es `eventhub-sistema`. Las variables son `{{marca}}` y `{{tono}}`.

```bash
python -m observability.prompts publicar
python -m observability.prompts comprobar
```

`publicar` crea la versión 1 con la etiqueta `production` y la versión 2 con la etiqueta `experimento`, solo si aún no existen. No llama a `update_prompt`. Langfuse mueve `latest` a la versión más nueva; eso no cambia `production`. Si el texto remoto ya no coincide con el repositorio, se detiene y no crea otra versión.

La versión 1 conserva el comportamiento de V4: tono profesional y formal, políticas, herramientas y prohibición de inventar. La versión 2 pide un tono cercano, respuestas concisas, reconocer los huecos y separar datos confirmados de suposiciones. Las dos incluyen las mismas instrucciones de `consultar_pedido` y `buscar_eventos`.

Para ejecutar una pregunta sin mover `production`:

```bash
python -m observability.langfuse_tracing --production --pregunta "¿Cuál es la política de devolución?"
python -m observability.langfuse_tracing --version 1 --pregunta "¿Cuál es la política de devolución?"
python -m observability.langfuse_tracing --version 2 --pregunta "¿Cuál es la política de devolución?"
```

`--version` solo admite 1 o 2. Cada traza lleva el nombre del prompt, su versión, la modalidad (`production`, `version-1` o `version-2`), la entrada y la respuesta. El enlace oficial es `propagate_attributes(prompt=...)`, además del metadato `langfuse_prompt` del `CallbackHandler`.

Los valores por defecto son `EventHub` y, según la versión descargada, `profesional y formal` o `cercano y conversacional`.

### Dataset y comparación de prompts

```bash
python -m observability.evaluacion
```

Crea, si no existe, el dataset `eventhub-12`: 4 políticas, 4 eventos y 4 pedidos. Las respuestas esperadas salen de `data/policies.md`, `data/events.json` y `data/orders.json`. Después ejecuta los mismos 12 casos con `eventhub-sistema` versión 1 y versión 2, pedidas por número. No usa `latest` ni mueve `production`.

Cada caso tiene un `session_id` nuevo. V4 no tiene checkpointer, y cada ejecución envía solo el mensaje nuevo. El modelo y las herramientas son los de V4; la diferencia es la versión del prompt.

Hay dos puntuaciones, ambas 1 o 0:

- `herramientas`: comprueba las llamadas reales del grafo. No mira el texto de la respuesta. Una política no exige herramienta. El email que no coincide prohíbe `buscar_eventos`.
- `juez`: el mismo `OPENAI_MODEL`, con salida Pydantic (`razonamiento`, `correcta`), compara la pregunta, la respuesta esperada y la generada. No exige el mismo texto. Una respuesta parcial, inventada o indecidible puntúa 0. No se fija otra temperatura: este modelo solo admite la de por defecto, igual que V4.

Los experimentos quedan como `eventhub-v1` y `eventhub-v2`. Hacen falta las mismas claves de OpenAI y Langfuse. Si faltan, el comando termina sin llamar al modelo.

### LangSmith

El trazado no se activa con un callback dentro de V4. El SDK 0.14.17 lee `LANGSMITH_TRACING`. Si no está, también acepta el nombre antiguo `LANGCHAIN_TRACING_V2`. Esta práctica solo usa los nombres `LANGSMITH_*` y no define los `LANGCHAIN_*`.

`cargar_entorno()` carga `.env` antes de ejecutar el grafo e invalida la caché del SDK. Sin eso, un import previo dejaría el trazado apagado aunque `.env` tuviera `LANGSMITH_TRACING=true`. La nube de Estados Unidos no necesita `LANGSMITH_ENDPOINT`. La europea sí: `https://eu.api.smith.langchain.com`.

Para repetir la comprobación y las dos evaluaciones:

```bash
python -m observability.langsmith_eval
```

Si faltan variables, termina sin llamar al modelo y no muestra la clave. El dataset es el mismo `eventhub-12`. Si ya coincide, no se duplica ni se reescribe. Las versiones 1 y 2 se piden por número a Langfuse. No se usa `latest` ni se mueve `production`. Cada caso tiene un `thread_id` nuevo. V4 no tiene checkpointer. Los evaluadores son los mismos: `herramientas` mira las llamadas reales y `juez` puntúa 0 o 1.

Ese comando ya se ejecutó contra la nube europea. Volver a lanzarlo crea otro experimento, porque el SDK añade un sufijo al nombre. Los resultados de abajo salen de la API, no de una segunda pasada.

Trazas del proyecto `thepower-eventhub`:

https://eu.smith.langchain.com/o/02cf41d8-bbc6-4074-8939-94ce0d1e8bfc/projects/p/33b93e9c-dff3-4b43-b1e0-76ded9f152b6

La traza `01a1eacf-46e5-75de-b6df-3d10694fa6f0` es una consulta real de conciertos en Valencia. La API muestra los nodos `chatbot`, `enrutar_despues_del_chatbot` y `herramientas`, la llamada `ChatOpenAI` y la herramienta `buscar_eventos`.

Dataset `eventhub-12`, 12 ejemplos idénticos a los locales:

https://eu.smith.langchain.com/o/02cf41d8-bbc6-4074-8939-94ce0d1e8bfc/datasets/b5cea9cb-8e9c-412f-81d7-cb8d32cbe598

Experimentos, 12 casos cada uno, prompt pedido por número:

- `eventhub-v1`: https://eu.smith.langchain.com/o/02cf41d8-bbc6-4074-8939-94ce0d1e8bfc/projects/p/61c6222f-87da-4743-821f-b38c80af705d
- `eventhub-v2`: https://eu.smith.langchain.com/o/02cf41d8-bbc6-4074-8939-94ce0d1e8bfc/projects/p/ef5a413c-5f52-4d9e-a726-d85db2b51411

La escala de las cuatro columnas es la media de 12 puntuaciones 0/1. Langfuse no se ha vuelto a ejecutar. Sus cifras salen de las capturas de la Parte 3. El juez es el mismo criterio, pero cada plataforma evaluó generaciones distintas, así que las puntuaciones no son el mismo experimento.

| Métrica | Langfuse V1 | Langfuse V2 | LangSmith V1 | LangSmith V2 |
| --- | ---: | ---: | ---: | ---: |
| Corrección LLM-as-a-judge | 0.833 | 0.750 | 0.583 | 0.667 |
| Uso correcto de herramientas | 1.000 | 1.000 | 1.000 | 1.000 |

En LangSmith, la versión 1 falló el juez en 5 casos y la versión 2 en 4. Los fallos repetidos son omisiones: la devolución no dice que no vale el mismo día, y los pedidos confirmado y cancelado no citan todos los identificadores esperados. La versión 2, además, inventó una comisión de 2 EUR en el reembolso, dato que esa respuesta esperada no fija. El uso de herramientas fue correcto en los 24 casos.

No se promociona la versión 2. `production` sigue en la versión 1, que es lo que pedía Langfuse, el sistema donde vive el prompt. La ventaja de la versión 2 en LangSmith es un caso (8/12 frente a 7/12) y no se repite en Langfuse. El tono más cercano no mejoró las herramientas y, en el reembolso, añadió un importe no pedido.

### Langfuse y LangSmith

Lo comprobado en esta práctica se separa de lo que dice la documentación y de lo que depende del plan.

| Criterio | Langfuse | LangSmith |
| --- | --- | --- |
| Facilidad de integración | Comprobado: hace falta `CallbackHandler` y `propagate_attributes` fuera del grafo, más las dos claves. V4 no importa el SDK. | Comprobado: basta `LANGSMITH_TRACING`, la clave, el proyecto y, en Europa, el endpoint. No se añadió un callback. El SDK 0.14.17 también lee `LANGCHAIN_*`; no se usan. |
| Visualización de trazas de grafos | Comprobado en la interfaz: la traza `s6-traza-10` muestra `chatbot`, `herramientas`, `consultar_pedido` y `buscar_eventos`. | Comprobado en la interfaz: la traza `01a1eacf-46e5-75de-b6df-3d10694fa6f0` muestra `chatbot`, `enrutar_despues_del_chatbot`, `herramientas`, `ChatOpenAI` y `buscar_eventos`. |
| Gestión de prompts | Comprobado: `eventhub-sistema`, versiones 1 y 2, etiqueta `production` en la 1 y `latest` en la 2. Pedir una versión no mueve `production`. | No se ha usado el hub de prompts de LangSmith. La documentación dice que la plataforma incluye prompt engineering. Aquí los prompts siguen en Langfuse. |
| Evaluaciones | Comprobado: dataset `eventhub-12` y experimentos `eventhub-v1` y `eventhub-v2`, con juez 0/1 y evaluador de herramientas. | Comprobado: el mismo dataset y los mismos nombres de experimento, mediante `Client.evaluate` en el SDK 0.14.17. |
| Opción de autoalojamiento | No se ha instalado. La documentación actual dice que es código abierto y se puede desplegar con Docker Compose o Kubernetes. Algunos complementos piden licencia. No se afirma que sea gratuito ni equivalente a la nube. | No se ha instalado. La documentación actual lo describe como complemento del plan Enterprise, con licencia y Kubernetes. No es la nube europea usada aquí ni una instalación gratuita. |

Capturas ya hechas, con la sesión en la región EU:

- `evidencias/s6_dataset_langsmith_evaluacion_v1.png`: experimento `eventhub-v1`, 12/12, herramientas 1.00 y juez 0.58.
- `evidencias/s6_dataset_langsmith_evaluacion_v2.png`: experimento `eventhub-v2`, 12/12, herramientas 1.00 y juez 0.67.
- `evidencias/s6_comparativa_langfuse_langsmith.png`: tabla de este README. No hay una vista única en ninguna de las dos plataformas que junte las cuatro columnas.
- `evidencias/s6_dataset_langsmith_12.png`: dataset `eventhub-12`, pestaña Examples, 12 ejemplos, con inputs, reference outputs y categoría.
- `evidencias/s6_langsmith_traza.png`: traza `01a1eacf-46e5-75de-b6df-3d10694fa6f0`, con `chatbot`, `enrutar_despues_del_chatbot`, `herramientas`, `ChatOpenAI` y `buscar_eventos`.

### V3 con PostgreSQL

```bash
python -m graphs.v3_postgres guardar
python -m graphs.v3_postgres recuperar
```

El segundo comando debe lanzarse en otro proceso, después de que el primero haya terminado. Así se comprueba que el historial no dependía de la memoria del intérprete.

Sin argumento, el módulo muestra estas dos formas de uso.

## Ejemplos de uso

V1, por reglas:

```text
Usuario: ¿Qué conciertos hay en la cartelera?
Intención: eventos
Nodo: responder_eventos
```

V2 y V3 conservan el turno anterior porque el estado es una lista de mensajes. Una comprobación habitual es decir el nombre y, en el siguiente turno, preguntar cómo te llamas.

V3 separa los hilos. Lo dicho en `conversacion_1` no aparece en `conversacion_2`.

V4, con los datos actuales:

```text
Usuario: Mi pedido es PED-1004 y el email es demo.madrid@correo-ficticio.test. ¿Es para un concierto en Madrid? Si es así, dime otros conciertos en Madrid ese mes.
```

El grafo consulta primero el pedido. Si el email coincide, el pedido devuelve `EVT-009`. Después busca conciertos en Madrid y puede citar los de junio que no son el del pedido: Jazz en el Retiro y Rock en La Latina. No debe incluir el concierto de julio.

`consultar_pedido` no muestra datos si falta el email o no coincide con el registrado. No inventa un correo.

La variante PostgreSQL guarda estos dos mensajes en `eventhub_postgres_demo`:

```text
Me llamo Ana y mi ciudad favorita es Madrid
Trabajo en el sector de la música y me gustan los conciertos
```

`recuperar` lee ese estado y después pregunta cómo te llamas, cuál es tu ciudad favorita y qué tipo de música te gusta. La respuesta tiene que salir de los mensajes persistidos. El segundo mensaje dice que te gustan los conciertos; no indica un género concreto.

## Datos de demostración

### `data/events.json`

Doce eventos ficticios. Cada uno tiene `id`, `nombre`, `ciudad`, `categoria`, `fecha`, `precio` y `disponibilidad`.

- `EVT-001` a `EVT-005`: conciertos en Valencia, entre junio y octubre de 2026.
- `EVT-006`: Feria del Libro de Otoño, Madrid, cultura, 18 de octubre de 2026.
- `EVT-007`: Maratón Nocturna del Puerto, Barcelona, deporte.
- `EVT-008`: Taller de Cocina Mediterránea, Sevilla, gastronomía.
- `EVT-009`: Noche Indie en Malasaña, Madrid, concierto, 12 de junio de 2026.
- `EVT-010`: Jazz en el Retiro, Madrid, concierto, 21 de junio de 2026.
- `EVT-011`: Rock en La Latina, Madrid, concierto, 27 de junio de 2026.
- `EVT-012`: Clásicos en el Auditorio, Madrid, concierto, 18 de julio de 2026.

### `data/orders.json`

Cuatro pedidos ficticios. Los correos son de demostración y están en el propio JSON.

- `PED-1001`: confirmado, `EVT-001` y `EVT-003`.
- `PED-1002`: pendiente, `EVT-006`.
- `PED-1003`: cancelado, `EVT-008`.
- `PED-1004`: confirmado, `EVT-009`, correo `demo.madrid@correo-ficticio.test`.

No existe ningún pedido `EH-1003`.

### `data/policies.md`

Normas ficticias de devoluciones, cancelaciones, cambios, reembolsos y plazos. V2 y las versiones posteriores las copian al prompt. No se consultan con una herramienta.

## Diagramas y evidencias

Los diagramas Mermaid están en `diagrams/`:

- `diagrams/v1_graph.mmd`: generado con `graph.get_graph().draw_mermaid()`.
- `diagrams/v4_graph.mmd`: mismos nodos y aristas que el grafo compilado de V4. Las aristas discontinuas son la decisión sobre `tool_calls`.

No hay diagrama de V2 ni de V3 porque su grafo es solo `START` → `chatbot` → `END`.

El informe escrito de Langfuse y LangSmith es `evidencias/langfuseysmith_ENTREGABLE.pdf`. Las capturas de esa parte también están en `evidencias/` (`s6_langfuse_*.png`, `s6_dataset_*.png`, `s6_langsmith_traza.png` y `s6_comparativa_langfuse_langsmith.png`). El resto de capturas de la rama son:

- `v1_diagrama.png` y `v1_pruebas.png`
- `v2_conversacion.png`
- `v3_memoria.png`
- `v3_postgres_guardar.png` y `v3_postgres_recuperar.png`
- `v4_conversacion.png` y `v4_diagrama.png`

Para ver un `.mmd`, usa la vista previa de Mermaid en VS Code o pega el contenido en [https://mermaid.live](https://mermaid.live).

## Limitaciones

- Los eventos, pedidos y políticas son ficheros locales. No hay una tienda real ni una base de datos de pedidos.
- PostgreSQL persiste checkpoints de LangGraph. No es el origen de los pedidos ni de la cartelera.
- V2 no puede consultar disponibilidad ni el estado de un pedido: el prompt indica que no tiene herramientas.
- V3 en memoria no sobrevive a otro proceso.
- `buscar_eventos` no filtra por mes ni por identificador. Devuelve el `id` y el mes lo deduce el modelo a partir de las fechas.
- `consultar_pedido` no devuelve el correo registrado y no muestra el pedido si el email no coincide.
- El identificador de modelo no se sustituye si la API lo rechaza.
- No hay interfaz web, API REST, autenticación ni despliegue.

## Solución de problemas

**`ModuleNotFoundError: langgraph` o `langchain_openai`.** El entorno virtual no está activo o falta la instalación. Ejecuta `source .venv/bin/activate` y `python -m pip install -r requirements.txt`.

**`No module named pytest`.** Las pruebas de V1 usan unittest, no pytest:

```bash
python -m unittest tests.test_v1_simple -v
```

**`OPENAI_API_KEY no está configurada`.** `.env` no está en la raíz o todavía contiene el valor de ejemplo. El programa no muestra la clave.

**La API rechaza `OPENAI_MODEL`.** El identificador no es válido para esa cuenta. Cámbialo en `.env`. El código no elige un modelo alternativo.

**`POSTGRES_URI no está configurada`.** Añade la variable en `.env`. Hace falta solo para `graphs/v3_postgres.py`.

**Error de conexión a PostgreSQL.** Comprueba que el servidor esté en marcha dentro de Ubuntu, que la base exista y que la URI sea alcanzable desde WSL. El mensaje del programa oculta usuario y contraseña. Si el fallo es de autenticación, revisa la URI sin pegarla en issues ni en capturas.

**`No module named langgraph.checkpoint.postgres` o `psycopg`.** Instala los paquetes adicionales indicados en la sección de instalación.

**V4 no encuentra las herramientas.** Tienen que existir `tools/events_tool.py` y `tools/orders_tool.py` en esta rama, y el comando debe lanzarse desde la raíz.

**Langfuse no está configurado.** Faltan las claves en `.env` o siguen siendo las de `.env.example`. `python -m graphs.v4_tools` no las necesita. El programa no muestra las claves.

**El pedido no se consulta.** El mensaje debe incluir un `id_pedido` que exista y el email asociado. Un email vacío produce «Faltan datos» y no llega a buscar eventos.

## Mejoras futuras

No están implementadas. Serían extensiones posibles:

- Añadir pruebas automáticas de V2, V3 y V4 que no dependan de una llamada real a la API.
- Exponer el grafo como API REST.
- Añadir una interfaz web.
- Consultar pedidos y eventos en una base de datos de negocio, distinta del checkpointer.
- Añadir autenticación.
- Incorporar nuevas herramientas, por ejemplo la reserva de entradas que existe en el proyecto LangChain anterior y aquí no se usa.
- Preparar un despliegue.

## Licencia y autoría

Licencia: pendiente de definir. Este repositorio no incluye un archivo `LICENSE`.

Autoría: pendiente de definir. No se ha añadido un nombre, una empresa ni un enlace que no conste en el proyecto.
