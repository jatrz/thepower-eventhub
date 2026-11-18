"""Evaluación de eventhub-12 en LangSmith, sin callbacks en el grafo.

La traza sale de LANGSMITH_TRACING=true. Este módulo no añade un callback
de LangSmith a la config del grafo ni usa la etiqueta latest. La etiqueta
production no se mueve. No llama al método que reescribe prompts.

API comprobada en langsmith 0.14.17: Client.evaluate, create_dataset,
has_dataset, create_examples y list_examples. evaluate añade un sufijo al
nombre; al terminar se intenta dejar el experimento como eventhub-v1 o
eventhub-v2. Si el nombre ya existe, se conserva el nombre único.
"""

from __future__ import annotations

import datetime
import sys
import uuid
from typing import Any

from graphs.v2_chatbot import ErrorConfiguracion, cargar_entorno
from observability.dataset import CASOS, NOMBRE_DATASET
from observability.evaluacion import (
    NOMBRE_DETERMINISTA,
    NOMBRE_JUEZ,
    calcular_metricas,
    como_lista,
    juzgar,
    puntuar_herramientas,
    puntuacion_de_juicio,
    recomendar,
)

EXPERIMENTO_V1 = "eventhub-v1"
EXPERIMENTO_V2 = "eventhub-v2"
NOMBRE_TRAZA = "eventhub-v4-langsmith"
PROYECTO_SUGERIDO = "thepower-eventhub"
PREGUNTA_TRAZA = next(caso.pregunta for caso in CASOS if caso.id == "evt-valencia-conciertos")

_PLACEHOLDERS = frozenset(
    {
        "",
        "pon_aqui_tu_api_key",
        "lsv2_pt_pon_aqui_tu_api_key",
    }
)
_LEGACY = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


def diagnostico_langsmith(valores: dict[str, str]) -> list[str]:
    """Devuelve problemas de configuración. No incluye el valor de ninguna clave."""
    problemas: list[str] = []
    if valores.get("LANGSMITH_TRACING", "").strip() != "true":
        problemas.append(
            "LANGSMITH_TRACING tiene que ser exactamente true. "
            "No se activa el trazado desde el código."
        )
    clave = valores.get("LANGSMITH_API_KEY", "").strip()
    if clave.lower() in _PLACEHOLDERS:
        problemas.append(
            "LANGSMITH_API_KEY no está configurada. "
            "Escríbela en .env. No la pegues en el chat. El valor no se muestra."
        )
    if not valores.get("LANGSMITH_PROJECT", "").strip():
        problemas.append(
            f"LANGSMITH_PROJECT no está configurada. Un valor válido es {PROYECTO_SUGERIDO}."
        )
    if any(valores.get(nombre, "").strip() for nombre in _LEGACY):
        problemas.append(
            "Hay variables antiguas LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY o "
            "LANGCHAIN_PROJECT. Este comando solo admite LANGSMITH_TRACING, "
            "LANGSMITH_API_KEY y LANGSMITH_PROJECT."
        )
    return problemas


def ejemplos_desde_casos() -> list[dict[str, Any]]:
    """Los mismos 12 casos, sin reescribir preguntas ni respuestas."""
    return [
        {
            "inputs": {"pregunta": caso.pregunta},
            "reference_outputs": {"respuesta": caso.esperada},
            "metadata": caso.metadata(),
        }
        for caso in CASOS
    ]


def referencia_de_ejemplo(ejemplo: Any) -> dict[str, Any]:
    salidas = getattr(ejemplo, "outputs", None)
    if isinstance(salidas, dict) and salidas:
        return salidas
    referencia = getattr(ejemplo, "reference_outputs", None)
    if isinstance(referencia, dict):
        return referencia
    if isinstance(ejemplo, dict):
        return ejemplo.get("reference_outputs") or ejemplo.get("outputs") or {}
    return {}


def metadatos_de_ejemplo(ejemplo: Any) -> dict[str, Any]:
    if isinstance(ejemplo, dict):
        meta = ejemplo.get("metadata") or {}
    else:
        meta = getattr(ejemplo, "metadata", None) or {}
    return meta if isinstance(meta, dict) else {}


def clasificar_dataset_remoto(ejemplos: list[Any]) -> str:
    """vacio, coincide o distinto. No borra ni duplica un dataset ya válido."""
    if not ejemplos:
        return "vacio"
    esperados = {caso.id: caso for caso in CASOS}
    vistos: dict[str, Any] = {}
    for ejemplo in ejemplos:
        caso_id = str(metadatos_de_ejemplo(ejemplo).get("id") or "")
        if caso_id in vistos or caso_id not in esperados:
            return "distinto"
        vistos[caso_id] = ejemplo
    if set(vistos) != set(esperados):
        return "distinto"
    for caso_id, ejemplo in vistos.items():
        caso = esperados[caso_id]
        meta = metadatos_de_ejemplo(ejemplo)
        entradas = ejemplo.inputs if not isinstance(ejemplo, dict) else ejemplo.get("inputs")
        if entradas != {"pregunta": caso.pregunta}:
            return "distinto"
        if referencia_de_ejemplo(ejemplo).get("respuesta") != caso.esperada:
            return "distinto"
        if como_lista(meta.get("herramientas_esperadas")) != list(caso.herramientas_esperadas):
            return "distinto"
        if como_lista(meta.get("herramientas_prohibidas")) != list(caso.herramientas_prohibidas):
            return "distinto"
        if meta.get("categoria") != caso.categoria:
            return "distinto"
    return "coincide"


def config_de_ejecucion(
    session_id: str,
    version: int,
    *,
    marca: str,
    tono: str,
    caso_id: str,
) -> dict[str, Any]:
    """Metadatos para la traza de entorno. No incluye callbacks."""
    return {
        "run_name": NOMBRE_TRAZA,
        "tags": [
            "eventhub",
            "langsmith",
            f"prompt-v{version}",
            f"modalidad-version-{version}",
        ],
        "metadata": {
            "prompt_nombre": "eventhub-sistema",
            "prompt_version": str(version),
            "prompt_modalidad": f"version-{version}",
            "session_id": session_id,
            "dataset_caso": caso_id,
            "marca": marca,
            "tono": tono,
        },
        "configurable": {"thread_id": session_id},
    }


def feedback_herramientas(salida: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Puntúa llamadas reales guardadas por el grafo, no el texto de la respuesta."""
    if salida.get("error"):
        return {
            "score": 0,
            "comment": (
                f"La ejecución falló ({salida.get('error')}). "
                "No se inventa una llamada correcta."
            ),
        }
    valor, comentario = puntuar_herramientas(
        como_lista(salida.get("herramientas")),
        como_lista(metadata.get("herramientas_esperadas")),
        como_lista(metadata.get("herramientas_prohibidas")),
    )
    return {"score": valor, "comment": comentario}


def feedback_juez(pregunta: str, esperada: str, salida: dict[str, Any]) -> dict[str, Any]:
    """Reutiliza el juez de la parte 3. Parcial o indecidible vale 0."""
    generada = str(salida.get("respuesta") or "").strip()
    if salida.get("error") or not generada:
        return {
            "score": 0,
            "comment": "No hay respuesta generada. No se fuerza una evaluación positiva.",
        }
    try:
        juicio = juzgar(pregunta, esperada, generada)
        valor, razon = puntuacion_de_juicio(juicio)
    except Exception as exc:
        return {
            "score": 0,
            "comment": f"El juez no devolvió la salida estructurada ({type(exc).__name__}).",
        }
    return {"score": valor, "comment": razon}


def herramientas(run: Any, example: Any) -> dict[str, Any]:
    """Evaluador de LangSmith. La clave visible es el nombre de la función."""
    salida = run.outputs if isinstance(getattr(run, "outputs", None), dict) else {}
    return feedback_herramientas(salida, metadatos_de_ejemplo(example))


def juez(run: Any, example: Any) -> dict[str, Any]:
    """Evaluador de LangSmith. Lee la respuesta del run, no un texto inventado."""
    salida = run.outputs if isinstance(getattr(run, "outputs", None), dict) else {}
    entradas = getattr(example, "inputs", None) or {}
    return feedback_juez(
        str(entradas.get("pregunta") or ""),
        str(referencia_de_ejemplo(example).get("respuesta") or ""),
        salida,
    )


def filas_de_resultados(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte filas de evaluate() al formato de calcular_metricas."""
    convertidas = []
    for fila in filas:
        resultados = (fila.get("evaluation_results") or {}).get("results") or []
        puntuaciones: dict[str, float] = {}
        for resultado in resultados:
            clave = resultado.get("key") if isinstance(resultado, dict) else getattr(resultado, "key", None)
            valor = resultado.get("score") if isinstance(resultado, dict) else getattr(resultado, "score", None)
            if clave is not None and valor is not None:
                puntuaciones[str(clave)] = float(valor)
        if NOMBRE_DETERMINISTA not in puntuaciones or NOMBRE_JUEZ not in puntuaciones:
            raise ErrorConfiguracion(
                "Un caso no tiene los dos evaluadores. No se calcula la media con un hueco."
            )
        salida = fila.get("run").outputs if fila.get("run") is not None else {}
        if not isinstance(salida, dict):
            salida = {}
        convertidas.append(
            {
                "determinista": puntuaciones[NOMBRE_DETERMINISTA],
                "juez": puntuaciones[NOMBRE_JUEZ],
                "error_ejecucion": bool(salida.get("error")),
            }
        )
    return convertidas


def _valores_entorno() -> dict[str, str]:
    import os

    nombres = ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", *_LEGACY)
    return {nombre: os.getenv(nombre, "") for nombre in nombres}


def preparar_entorno_langsmith() -> str:
    """Carga .env, limpia la caché de LangSmith y exige trazado por entorno."""
    cargar_entorno()
    from langsmith.utils import get_env_var, tracing_is_enabled

    get_env_var.cache_clear()
    problemas = diagnostico_langsmith(_valores_entorno())
    if problemas:
        raise ErrorConfiguracion("\n".join(problemas))
    if not tracing_is_enabled():
        raise ErrorConfiguracion(
            "LangSmith no considera activa la traza tras leer el entorno. "
            "No se llama al modelo."
        )
    proyecto = _valores_entorno()["LANGSMITH_PROJECT"].strip()
    return proyecto


def _cliente():
    from langsmith import Client

    return Client()


def _caso_id(pregunta: str) -> str:
    for caso in CASOS:
        if caso.pregunta == pregunta:
            return caso.id
    return "caso"


def _anotar_traza(session_id: str, version: int, caso_id: str) -> None:
    try:
        from langsmith.run_helpers import get_current_run_tree
    except Exception:
        return
    arbol = get_current_run_tree()
    if arbol is None:
        return
    extra = {
        "prompt_nombre": "eventhub-sistema",
        "prompt_version": str(version),
        "prompt_modalidad": f"version-{version}",
        "session_id": session_id,
        "dataset_caso": caso_id,
    }
    metadatos = getattr(arbol, "metadata", None)
    if isinstance(metadatos, dict):
        metadatos.update(extra)
    etiquetas = list(getattr(arbol, "tags", None) or [])
    for etiqueta in (f"prompt-v{version}", f"modalidad-version-{version}"):
        if etiqueta not in etiquetas:
            etiquetas.append(etiqueta)
    try:
        arbol.tags = etiquetas
    except Exception:
        return


def _responder(graph, prompt, marca: str, tono: str, version: int, pregunta: str) -> dict[str, Any]:
    from graphs.v4_tools import _respuesta_final, _usos_de_herramientas, ejecutar_consulta

    caso_id = _caso_id(pregunta)
    session_id = f"s6-ls-v{version}-{caso_id}-{uuid.uuid4().hex[:8]}"
    _anotar_traza(session_id, version, caso_id)
    try:
        mensajes, limite = ejecutar_consulta(
            graph,
            pregunta,
            config=config_de_ejecucion(
                session_id,
                version,
                marca=marca,
                tono=tono,
                caso_id=caso_id,
            ),
        )
    except Exception as exc:
        return {
            "respuesta": "",
            "error": type(exc).__name__,
            "herramientas": [],
            "prompt_nombre": prompt.name,
            "prompt_version": prompt.version,
            "prompt_modalidad": f"version-{version}",
            "session_id": session_id,
            "limite": False,
        }
    usos = _usos_de_herramientas(mensajes)
    return {
        "respuesta": _respuesta_final(mensajes),
        "herramientas": [nombre for nombre, _, _ in usos],
        "prompt_nombre": prompt.name,
        "prompt_version": prompt.version,
        "prompt_modalidad": f"version-{version}",
        "session_id": session_id,
        "limite": limite,
    }


def asegurar_dataset(cliente) -> str:
    """Crea eventhub-12 solo si no existe. Si ya coincide, no añade ítems."""
    if not cliente.has_dataset(dataset_name=NOMBRE_DATASET):
        cliente.create_dataset(
            NOMBRE_DATASET,
            description=(
                "12 casos reales de EventHub: 4 políticas, 4 eventos y 4 pedidos. "
                "Las respuestas salen de data/policies.md, data/events.json y data/orders.json."
            ),
            metadata={"origen": "observability/dataset.py", "casos": 12},
        )
    ejemplos = list(cliente.list_examples(dataset_name=NOMBRE_DATASET))
    estado = clasificar_dataset_remoto(ejemplos)
    if estado == "coincide":
        return "ya-coincidia"
    if estado == "distinto":
        raise ErrorConfiguracion(
            "El dataset eventhub-12 ya existe en LangSmith y no coincide con los 12 casos locales. "
            "No se duplica ni se borra."
        )
    cliente.create_examples(dataset_name=NOMBRE_DATASET, examples=ejemplos_desde_casos())
    comprobacion = list(cliente.list_examples(dataset_name=NOMBRE_DATASET))
    if clasificar_dataset_remoto(comprobacion) != "coincide":
        raise ErrorConfiguracion(
            "Tras crear los ejemplos, eventhub-12 no tiene exactamente los 12 casos esperados."
        )
    return "creado"


def _cerrar_con_nombre(cliente, experimento_id, nombre: str) -> str:
    """Intenta el nombre pedido. Si está ocupado, deja el nombre único del SDK."""
    ahora = datetime.datetime.now(datetime.timezone.utc)
    try:
        actualizado = cliente.update_project(experimento_id, name=nombre, end_time=ahora)
    except Exception:
        return ""
    return str(getattr(actualizado, "name", "") or "")


def _evaluar_version(cliente, version: int, nombre: str) -> dict[str, Any]:
    from langsmith import evaluate

    from observability.prompts import seleccionar_y_compilar

    graph, prompt, marca, tono = seleccionar_y_compilar(version, marca=None, tono=None)
    if prompt.version != version:
        raise ErrorConfiguracion(
            f"Se pidió la versión {version} por número y Langfuse devolvió la {prompt.version}. "
            "No se evalúa con latest ni se reetiqueta."
        )

    def predecir(inputs: dict) -> dict[str, Any]:
        return _responder(graph, prompt, marca, tono, version, str(inputs.get("pregunta") or ""))

    resultados = evaluate(
        predecir,
        data=NOMBRE_DATASET,
        evaluators=[herramientas, juez],
        experiment_prefix=nombre,
        description=(
            f"eventhub-12 con eventhub-sistema versión {version} pedida por número. "
            "No usa production ni latest. El modelo y las herramientas son los de V4."
        ),
        max_concurrency=1,
        client=cliente,
        metadata={
            "prompt_nombre": prompt.name,
            "prompt_version": str(prompt.version),
            "prompt_modalidad": f"version-{version}",
            "dataset": NOMBRE_DATASET,
        },
    )
    nombre_final = _cerrar_con_nombre(cliente, resultados.experiment_id, nombre) or resultados.experiment_name
    filas = filas_de_resultados(list(resultados))
    if len(filas) != 12:
        raise ErrorConfiguracion(
            f"La versión {version} no ha evaluado 12 casos. No se publica una media parcial."
        )
    metricas = calcular_metricas(filas)
    metricas["experimento"] = nombre_final
    metricas["url"] = resultados.url
    metricas["prompt_version"] = prompt.version
    return metricas


def _metadatos_de_run(run: Any) -> dict[str, Any]:
    extra = getattr(run, "extra", None) or {}
    if isinstance(extra, dict) and isinstance(extra.get("metadata"), dict):
        return extra["metadata"]
    metadatos = getattr(run, "metadata", None)
    return metadatos if isinstance(metadatos, dict) else {}


def traza_de_herramienta(runs: list[Any], *, session_id: str) -> dict[str, Any] | None:
    """Confirma una traza real con la pregunta y una llamada a buscar_eventos."""
    raices = []
    for run in runs:
        meta = _metadatos_de_run(run)
        if meta.get("session_id") != session_id:
            continue
        if getattr(run, "name", "") == NOMBRE_TRAZA or meta.get("dataset_caso") == "evt-valencia-conciertos":
            raices.append(run)
    if not raices:
        return None
    raiz = raices[0]
    traza = str(getattr(raiz, "trace_id", "") or getattr(raiz, "id", ""))
    hijas = [
        run
        for run in runs
        if str(getattr(run, "trace_id", "")) == traza and getattr(run, "name", "") == "buscar_eventos"
    ]
    if not hijas:
        return None
    return {
        "run_id": str(getattr(raiz, "id", "")),
        "trace_id": traza,
        "nombre": getattr(raiz, "name", ""),
        "herramienta": "buscar_eventos",
    }


def ejecutar_traza_de_comprobacion(cliente, proyecto: str) -> dict[str, Any]:
    """Una consulta real con herramienta. No crea el experimento de 12 casos."""
    from observability.prompts import seleccionar_y_compilar

    graph, prompt, marca, tono = seleccionar_y_compilar(1, marca=None, tono=None)
    if prompt.version != 1:
        raise ErrorConfiguracion("La traza de comprobación tenía que usar la versión 1 pedida por número.")
    salida = _responder(graph, prompt, marca, tono, 1, PREGUNTA_TRAZA)
    if salida.get("error") or "buscar_eventos" not in salida.get("herramientas", []):
        raise ErrorConfiguracion(
            "La consulta de comprobación no llamó a buscar_eventos. "
            "No se da por válida la traza de LangSmith."
        )
    session_id = salida["session_id"]
    import time

    confirmada = None
    for _ in range(6):
        time.sleep(2)
        raices = list(
            cliente.list_runs(
                project_name=proyecto,
                filter=f'eq(name, "{NOMBRE_TRAZA}")',
                limit=30,
            )
        )
        for raiz in raices:
            if _metadatos_de_run(raiz).get("session_id") != session_id:
                continue
            hijas = list(cliente.list_runs(project_name=proyecto, trace_id=raiz.trace_id, limit=50))
            confirmada = traza_de_herramienta([raiz, *hijas], session_id=session_id)
            if confirmada:
                break
        if confirmada:
            break
    if confirmada is None:
        raise ErrorConfiguracion(
            "La consulta se ejecutó, pero la API de LangSmith no devolvió una traza "
            "con buscar_eventos para esa sesión. No se inventa el identificador."
        )
    confirmada["session_id"] = session_id
    confirmada["prompt_version"] = salida["prompt_version"]
    confirmada["proyecto"] = proyecto
    return confirmada


def ejecutar() -> dict[str, Any]:
    """Comprueba una traza y evalúa las dos versiones. No mueve production."""
    from observability.config import langfuse_esta_configurado
    from observability.prompts import comprobar_remoto

    proyecto = preparar_entorno_langsmith()
    if not langfuse_esta_configurado():
        raise ErrorConfiguracion(
            "Langfuse no está configurado. Hace falta para recuperar el prompt. No se muestran las claves."
        )
    antes = comprobar_remoto()
    if antes["produccion"] != 1 or "production" in antes["etiquetas_v2"]:
        raise ErrorConfiguracion(
            "production no está en la versión 1. No se ejecuta LangSmith ni se reetiqueta."
        )
    cliente = _cliente()
    traza = ejecutar_traza_de_comprobacion(cliente, proyecto)
    estado_dataset = asegurar_dataset(cliente)
    v1 = _evaluar_version(cliente, 1, EXPERIMENTO_V1)
    v2 = _evaluar_version(cliente, 2, EXPERIMENTO_V2)
    despues = comprobar_remoto()
    if despues["produccion"] != 1 or "production" in despues["etiquetas_v2"]:
        raise ErrorConfiguracion(
            "La etiqueta production ha cambiado durante la evaluación. Revisa Langfuse antes de continuar."
        )
    return {
        "proyecto": proyecto,
        "traza": traza,
        "dataset": estado_dataset,
        "antes": antes,
        "despues": despues,
        "v1": v1,
        "v2": v2,
        "recomendacion": recomendar(v1, v2),
    }


def _imprimir(resumen: dict[str, Any]) -> None:
    traza = resumen["traza"]
    print(f"proyecto: {resumen['proyecto']}")
    print(
        "traza de comprobación: "
        f"run={traza['run_id']} trace={traza['trace_id']} "
        f"prompt=v{traza['prompt_version']} herramienta={traza['herramienta']}"
    )
    print(f"dataset: {NOMBRE_DATASET} ({resumen['dataset']})")
    print(
        "production antes/después: "
        f"v{resumen['antes']['produccion']} / v{resumen['despues']['produccion']}"
    )
    print("métrica | prompt v1 | prompt v2")
    v1 = resumen["v1"]
    v2 = resumen["v2"]
    print(f"casos evaluados | {v1['casos']} | {v2['casos']}")
    print(f"media determinista | {v1['media_determinista']:.3f} | {v2['media_determinista']:.3f}")
    print(f"media LLM juez | {v1['media_juez']:.3f} | {v2['media_juez']:.3f}")
    print(
        "respuestas correctas (%) | "
        f"{v1['respuestas_correctas_pct']:.1f} | {v2['respuestas_correctas_pct']:.1f}"
    )
    print(f"número de errores | {v1['errores']} | {v2['errores']}")
    print(
        "herramientas incorrectas | "
        f"{v1['herramientas_incorrectas']} | {v2['herramientas_incorrectas']}"
    )
    print(f"recomendación según LangSmith: {resumen['recomendacion']}")
    print("No se ha cambiado la etiqueta production.")
    print(f"experimento v1: {v1['experimento']} {v1['url'] or 'sin url'}")
    print(f"experimento v2: {v2['experimento']} {v2['url'] or 'sin url'}")


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("Uso: python -m observability.langsmith_eval")
        print("No admite argumentos. Evalúa eventhub-12 con las versiones 1 y 2.")
        return 2
    try:
        _imprimir(ejecutar())
    except ErrorConfiguracion as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        import re

        texto = re.sub(r"lsv2_[A-Za-z0-9_]+", "[clave-oculta]", str(exc))
        print(
            f"No se ha podido completar la evaluación de LangSmith.\n{type(exc).__name__}: {texto}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
