"""Evaluación comparativa de las versiones 1 y 2 de eventhub-sistema.

Recupera cada versión por número, no por la etiqueta production ni por latest.
No llama a update_prompt. Cada caso usa un hilo nuevo. V4 no tiene checkpointer,
así que una ejecución no hereda mensajes de otra.

El evaluador determinista mira las llamadas reales del grafo, no el texto final.
El juez compara pregunta, respuesta esperada y respuesta generada. Si la
respuesta es parcial o no se puede decidir, la puntuación es 0. No se fuerza
un resultado positivo ni se exige coincidencia literal.

Puntuación de los dos evaluadores: 1 correcto, 0 incorrecto.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from pydantic import BaseModel

from graphs.v2_chatbot import ErrorConfiguracion
from observability.dataset import NOMBRE_DATASET, publicar_dataset

EXPERIMENTO_V1 = "eventhub-v1"
EXPERIMENTO_V2 = "eventhub-v2"
NOMBRE_DETERMINISTA = "herramientas"
NOMBRE_JUEZ = "juez"

_CRITERIO_JUEZ = (
    "No exijas coincidencia literal. Valora corrección factual, correspondencia "
    "con la respuesta esperada, ausencia de información inventada, respeto de las "
    "políticas y datos reales, y utilidad. correcta es true solo si cubre los hechos "
    "necesarios y no los contradice. Una omisión necesaria, un dato inventado o una "
    "respuesta solo parcial hacen que correcta sea false. Si no se puede decidir, "
    "correcta es false. No fuerces una evaluación positiva."
)


class Juicio(BaseModel):
    """Salida estructurada del juez. No admite otros campos."""

    razonamiento: str
    correcta: bool


def como_lista(valor: Any) -> list[str]:
    """Normaliza una lista de herramientas venga como lista o como texto."""
    if valor is None or valor == "":
        return []
    if isinstance(valor, str):
        return [parte.strip() for parte in valor.split(",") if parte.strip()]
    if isinstance(valor, (list, tuple)):
        return [str(parte) for parte in valor if str(parte).strip()]
    return [str(valor)]


def puntuar_herramientas(
    usadas: list[str],
    esperadas: list[str],
    prohibidas: list[str],
) -> tuple[int, str]:
    """1 solo si están todas las esperadas y ninguna prohibida.

    Una pregunta de políticas no espera herramientas. Llamar a una de más no
    baja la puntuación, salvo que esa herramienta esté prohibida. El email que
    no coincide prohíbe buscar_eventos: el prompt impide seguir buscando.
    """
    usadas_orden = [nombre for nombre in usadas if nombre]
    presentes = set(usadas_orden)
    faltan = [nombre for nombre in esperadas if nombre not in presentes]
    indebidas = [nombre for nombre in prohibidas if nombre in presentes]
    comentario = (
        f"esperadas: {', '.join(esperadas) or 'ninguna'}; "
        f"usadas: {', '.join(usadas_orden) or 'ninguna'}; "
        f"prohibidas: {', '.join(prohibidas) or 'ninguna'}"
    )
    if faltan or indebidas:
        return 0, comentario + (
            f"; faltan: {', '.join(faltan) or 'ninguna'}; "
            f"indebidas: {', '.join(indebidas) or 'ninguna'}"
        )
    return 1, comentario


def evaluar_herramientas(*, output: Any, metadata: dict | None, **kwargs: Any):
    """Lee las herramientas registradas por el grafo, no palabras de la respuesta."""
    from langfuse import Evaluation

    datos = output if isinstance(output, dict) else {}
    meta = metadata or {}
    if datos.get("error"):
        return Evaluation(
            name=NOMBRE_DETERMINISTA,
            value=0,
            comment=f"La ejecución falló ({datos.get('error')}). No se inventa una llamada correcta.",
            metadata={"usadas": [], "esperadas": como_lista(meta.get("herramientas_esperadas"))},
        )
    usadas = como_lista(datos.get("herramientas"))
    esperadas = como_lista(meta.get("herramientas_esperadas"))
    prohibidas = como_lista(meta.get("herramientas_prohibidas"))
    valor, comentario = puntuar_herramientas(usadas, esperadas, prohibidas)
    return Evaluation(
        name=NOMBRE_DETERMINISTA,
        value=valor,
        comment=comentario,
        metadata={"usadas": usadas, "esperadas": esperadas, "prohibidas": prohibidas},
    )


def puntuacion_de_juicio(juicio: Juicio) -> tuple[int, str]:
    """Convierte el booleano en 0 o 1 y conserva el razonamiento."""
    razon = " ".join(juicio.razonamiento.split())
    if not razon:
        return 0, "El juez no ha explicado la evaluación. No se fuerza un positivo."
    return (1 if juicio.correcta else 0), razon


def evaluar_con_juez(*, input: Any, output: Any, expected_output: Any, **kwargs: Any):
    """Compara pregunta, respuesta esperada y respuesta generada."""
    from langfuse import Evaluation

    datos = output if isinstance(output, dict) else {}
    generada = str(datos.get("respuesta") or "").strip()
    if datos.get("error") or not generada:
        return Evaluation(
            name=NOMBRE_JUEZ,
            value=0,
            comment="No hay respuesta generada. No se fuerza una evaluación positiva.",
            metadata={"correcta": False, "criterio": "sin-respuesta"},
        )
    try:
        juicio = juzgar(str(input), str(expected_output or ""), generada)
        valor, razon = puntuacion_de_juicio(juicio)
    except Exception as exc:
        return Evaluation(
            name=NOMBRE_JUEZ,
            value=0,
            comment=f"El juez no devolvió la salida estructurada ({type(exc).__name__}).",
            metadata={"correcta": False, "criterio": "salida-no-estructurada"},
        )
    return Evaluation(
        name=NOMBRE_JUEZ,
        value=valor,
        comment=razon,
        metadata={"correcta": juicio.correcta, "criterio": "parcial-es-incorrecta"},
    )


def juzgar(pregunta: str, esperada: str, generada: str) -> Juicio:
    """Llama al mismo modelo configurado y exige una salida Pydantic.

    No fija la temperatura: el modelo de esta cuenta solo admite el valor por
    defecto, que es el mismo que usa V4. No se cambia a otro modelo.
    """
    from graphs.v2_chatbot import leer_configuracion
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    api_key, modelo = leer_configuracion()
    cliente = ChatOpenAI(
        model=modelo,
        api_key=api_key,
        timeout=60,
        max_retries=1,
    )
    estructurado = cliente.with_structured_output(Juicio)
    resultado = estructurado.invoke(
        [
            SystemMessage(
                content=(
                    "Eres un evaluador del asistente EventHub. No respondas al usuario. "
                    + _CRITERIO_JUEZ
                )
            ),
            HumanMessage(
                content=(
                    f"Pregunta:\n{pregunta}\n\n"
                    f"Respuesta esperada:\n{esperada}\n\n"
                    f"Respuesta generada:\n{generada}"
                )
            ),
        ]
    )
    if isinstance(resultado, Juicio):
        return resultado
    return Juicio.model_validate(resultado)


def calcular_metricas(filas: list[dict[str, Any]]) -> dict[str, float | int]:
    """Medias sobre casos realmente evaluados. No rellena huecos con un acierto."""
    if not filas:
        raise ErrorConfiguracion("No hay casos evaluados. No se calcula una media ficticia.")
    deterministas = [float(fila["determinista"]) for fila in filas]
    jueces = [float(fila["juez"]) for fila in filas]
    errores = sum(1 for fila in filas if fila["juez"] != 1 or fila.get("error_ejecucion"))
    herramientas_incorrectas = sum(1 for fila in filas if fila["determinista"] != 1)
    return {
        "casos": len(filas),
        "media_determinista": sum(deterministas) / len(filas),
        "media_juez": sum(jueces) / len(filas),
        "respuestas_correctas_pct": 100.0 * sum(1 for valor in jueces if valor == 1) / len(filas),
        "errores": errores,
        "herramientas_incorrectas": herramientas_incorrectas,
    }


def recomendar(version_1: dict[str, Any], version_2: dict[str, Any]) -> str:
    """Elige con las medias reales. Si no hay mejora, se mantiene la versión 1.

    No cambia etiquetas. Primero manda el juez; si empata, el evaluador de
    herramientas. Un empate total no justifica mover production.
    """
    if version_2["media_juez"] > version_1["media_juez"]:
        return "v2"
    if version_2["media_juez"] < version_1["media_juez"]:
        return "v1"
    if version_2["media_determinista"] > version_1["media_determinista"]:
        return "v2"
    if version_2["media_determinista"] < version_1["media_determinista"]:
        return "v1"
    return "empate-mantener-v1"


def ejecutar_experimentos() -> dict[str, Any]:
    """Publica el dataset si falta y evalúa las dos versiones con los mismos 12 casos."""
    from langfuse import get_client

    from observability.config import langfuse_esta_configurado, preparar_entorno_langfuse
    from observability.prompts import comprobar_remoto

    if not langfuse_esta_configurado():
        raise ErrorConfiguracion(
            "Langfuse no está configurado. No se ejecuta la evaluación ni se muestran las claves."
        )
    preparar_entorno_langfuse()
    cliente = get_client()
    if not cliente.auth_check():
        raise ErrorConfiguracion("Langfuse ha rechazado las credenciales. No se muestra ninguna clave.")

    antes = comprobar_remoto()
    if antes["produccion"] != 1 or "production" in antes["etiquetas_v2"]:
        raise ErrorConfiguracion(
            "production no está en la versión 1. No se ejecuta la comparación ni se reetiqueta."
        )
    estado_dataset = publicar_dataset()
    dataset = cliente.get_dataset(NOMBRE_DATASET, fetch_items_page_size=50)
    if len(list(dataset.items)) != 12:
        raise ErrorConfiguracion("El dataset remoto no tiene 12 casos. No se lanzan los experimentos.")

    resultado_v1 = _ejecutar_version(dataset, 1, EXPERIMENTO_V1)
    resultado_v2 = _ejecutar_version(dataset, 2, EXPERIMENTO_V2)
    despues = comprobar_remoto()
    if despues["produccion"] != 1 or "production" in despues["etiquetas_v2"]:
        raise ErrorConfiguracion(
            "La comparación ha movido production. Hay que revisarlo antes de usar los resultados."
        )
    cliente.flush()
    metricas_v1 = _metricas_de_resultado(resultado_v1)
    metricas_v2 = _metricas_de_resultado(resultado_v2)
    return {
        "dataset": estado_dataset,
        "antes": antes,
        "despues": despues,
        "v1": metricas_v1,
        "v2": metricas_v2,
        "recomendacion": recomendar(metricas_v1, metricas_v2),
        "url_v1": resultado_v1.experiment_url,
        "url_v2": resultado_v2.experiment_url,
        "detalle_v1": _detalle(resultado_v1),
        "detalle_v2": _detalle(resultado_v2),
    }


def _ejecutar_version(dataset, version: int, nombre: str):
    from observability.prompts import seleccionar_y_compilar

    graph, prompt, marca, tono = seleccionar_y_compilar(version, marca=None, tono=None)
    if prompt.version != version or prompt.name != "eventhub-sistema":
        raise ErrorConfiguracion(
            f"Se pidió la versión {version} y Langfuse ha devuelto otra. No se usa latest ni production."
        )
    if version == 2 and "production" in prompt.labels:
        raise ErrorConfiguracion("La versión 2 trae production. No se ejecuta el experimento.")

    def tarea(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        return _responder_item(
            item,
            graph=graph,
            prompt=prompt,
            marca=marca,
            tono=tono,
            version=version,
        )

    return dataset.run_experiment(
        name=nombre,
        run_name=nombre,
        description=(
            f"eventhub-12 con eventhub-sistema versión {version} pedida por número. "
            "No usa la etiqueta production ni latest. El modelo y las herramientas son los de V4."
        ),
        task=tarea,
        evaluators=[evaluar_herramientas, evaluar_con_juez],
        run_evaluators=[evaluar_medias],
        max_concurrency=1,
        metadata={
            "prompt_nombre": prompt.name,
            "prompt_version": str(prompt.version),
            "prompt_modalidad": f"version-{version}",
            "dataset": NOMBRE_DATASET,
        },
    )


def _responder_item(item: Any, *, graph, prompt, marca: str, tono: str, version: int) -> dict[str, Any]:
    from langfuse import get_client

    from graphs.v4_tools import _respuesta_final, _usos_de_herramientas
    from observability.langfuse_tracing import ejecutar_consulta_trazada

    pregunta, metadata = _campos_item(item)
    caso_id = str((metadata or {}).get("id") or "caso")
    session_id = f"s6-eval-v{version}-{caso_id}-{uuid.uuid4().hex[:8]}"
    try:
        get_client().update_current_span(
            metadata={
                "prompt_nombre": prompt.name,
                "prompt_version": str(prompt.version),
                "prompt_modalidad": f"version-{version}",
                "dataset_caso": caso_id,
                "session_id": session_id,
            }
        )
    except Exception:
        # El experimento sigue: la versión también va en la salida y en los metadatos del run.
        pass
    try:
        mensajes, limite, trace_id = ejecutar_consulta_trazada(
            graph,
            str(pregunta),
            session_id=session_id,
            prompt_cliente=prompt,
            modalidad=f"version-{version}",
            marca=marca,
            tono=tono,
        )
    except Exception as exc:
        return {
            "respuesta": "",
            "error": type(exc).__name__,
            "herramientas": [],
            "usos": [],
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
        "usos": [{"nombre": nombre, "argumentos": argumentos} for nombre, argumentos, _ in usos],
        "prompt_nombre": prompt.name,
        "prompt_version": prompt.version,
        "prompt_etiquetas": list(prompt.labels),
        "prompt_modalidad": f"version-{version}",
        "session_id": session_id,
        "trace_id_grafo": trace_id,
        "limite": limite,
    }


def _campos_item(item: Any) -> tuple[Any, dict]:
    if isinstance(item, dict):
        metadata = item.get("metadata") or {}
        return item.get("input"), metadata if isinstance(metadata, dict) else {}
    metadata = getattr(item, "metadata", None) or {}
    return getattr(item, "input", None), metadata if isinstance(metadata, dict) else {}


def evaluar_medias(*, item_results: list, **kwargs: Any):
    """Registra las medias del run. No sustituye el cálculo local si falta un caso."""
    from langfuse import Evaluation

    filas = []
    for resultado in item_results:
        puntuaciones = {evaluacion.name: evaluacion.value for evaluacion in resultado.evaluations}
        if NOMBRE_DETERMINISTA not in puntuaciones or NOMBRE_JUEZ not in puntuaciones:
            continue
        salida = resultado.output if isinstance(resultado.output, dict) else {}
        filas.append(
            {
                "determinista": puntuaciones[NOMBRE_DETERMINISTA],
                "juez": puntuaciones[NOMBRE_JUEZ],
                "error_ejecucion": bool(salida.get("error")),
            }
        )
    if len(filas) != len(item_results):
        return Evaluation(
            name="media_juez",
            value=0,
            comment="Faltan evaluaciones de algún caso. No se publica una media parcial como si fuera completa.",
        )
    metricas = calcular_metricas(filas)
    return [
        Evaluation(name="media_herramientas", value=metricas["media_determinista"]),
        Evaluation(
            name="media_juez",
            value=metricas["media_juez"],
            comment=f"respuestas correctas: {metricas['respuestas_correctas_pct']:.1f}%",
        ),
    ]


def _metricas_de_resultado(resultado) -> dict[str, Any]:
    filas = []
    for item in resultado.item_results:
        puntuaciones = {evaluacion.name: evaluacion.value for evaluacion in item.evaluations}
        if NOMBRE_DETERMINISTA not in puntuaciones or NOMBRE_JUEZ not in puntuaciones:
            raise ErrorConfiguracion(
                "Un caso no tiene los dos evaluadores. No se calcula la media con un hueco."
            )
        salida = item.output if isinstance(item.output, dict) else {}
        filas.append(
            {
                "determinista": puntuaciones[NOMBRE_DETERMINISTA],
                "juez": puntuaciones[NOMBRE_JUEZ],
                "error_ejecucion": bool(salida.get("error")),
            }
        )
    metricas = calcular_metricas(filas)
    metricas["run_name"] = resultado.run_name
    metricas["experiment_id"] = resultado.experiment_id
    return metricas


def _detalle(resultado) -> list[dict[str, Any]]:
    filas = []
    for item in resultado.item_results:
        pregunta, metadata = _campos_item(item.item)
        salida = item.output if isinstance(item.output, dict) else {"respuesta": str(item.output)}
        puntuaciones = {evaluacion.name: evaluacion for evaluacion in item.evaluations}
        juez = puntuaciones.get(NOMBRE_JUEZ)
        herramientas = puntuaciones.get(NOMBRE_DETERMINISTA)
        filas.append(
            {
                "id": (metadata or {}).get("id"),
                "pregunta": pregunta,
                "esperada": getattr(item.item, "expected_output", None),
                "respuesta": salida.get("respuesta", ""),
                "prompt_version": salida.get("prompt_version"),
                "herramientas": salida.get("herramientas", []),
                "determinista": None if herramientas is None else herramientas.value,
                "juez": None if juez is None else juez.value,
                "razonamiento": "" if juez is None else juez.comment,
                "trace_id": item.trace_id,
                "error": salida.get("error"),
            }
        )
    return filas


def _imprimir(resumen: dict[str, Any]) -> None:
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
    print(f"recomendación según resultados: {resumen['recomendacion']}")
    print("No se ha cambiado la etiqueta production.")
    print(f"experimento v1: {resumen['url_v1'] or 'sin url'}")
    print(f"experimento v2: {resumen['url_v2'] or 'sin url'}")
    for etiqueta, detalle in (("v1", resumen["detalle_v1"]), ("v2", resumen["detalle_v2"])):
        print(f"detalle {etiqueta}:")
        for fila in detalle:
            print(
                f"  {fila['id']}: herramientas={fila['determinista']} "
                f"juez={fila['juez']} usadas={','.join(fila['herramientas']) or 'ninguna'} "
                f"traza={fila['trace_id'] or 'sin id'}"
            )


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("Uso: python -m observability.evaluacion")
        print("No admite argumentos. Evalúa eventhub-12 con las versiones 1 y 2.")
        return 2
    try:
        _imprimir(ejecutar_experimentos())
    except ErrorConfiguracion as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"No se ha podido completar la evaluación.\n{type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
