"""Grafo V4 de EventHub: chatbot con herramientas y ciclo de vuelta al modelo.

buscar_eventos y consultar_pedido viven en tools/ de esta rama y leen los JSON
locales. Ya no se cargan desde el repositorio hermano de LangChain.
"""

from __future__ import annotations

import sys
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from openai import OpenAIError

from graphs.v2_chatbot import (
    RAIZ_PROYECTO,
    RUTA_POLITICAS,
    ErrorConfiguracion,
    construir_prompt_sistema,
    crear_modelo,
    interpretar_error_api,
    leer_configuracion,
    leer_politicas,
    ruta_visible,
    texto_de_mensaje,
)
from tools.events_tool import buscar_eventos
from tools.orders_tool import consultar_pedido

NODO_CHATBOT = "chatbot"
NODO_HERRAMIENTAS = "herramientas"
# Cabe una consulta de pedido, una búsqueda de eventos y la respuesta final.
# Un bucle de herramientas se detiene antes de seguir indefinidamente.
LIMITE_PASOS = 12
CONSULTA_DEMO = (
    "Mi pedido es PED-1004 y el email es demo.madrid@correo-ficticio.test. "
    "¿Es para un concierto en Madrid? Si es así, dime otros conciertos en Madrid ese mes."
)
MENSAJE_LIMITE = (
    "Se ha alcanzado el límite de pasos del grafo. "
    "La consulta se detiene para evitar un bucle infinito de herramientas."
)

# Párrafo de V2 que niega el acceso a datos. En V4 se sustituye solo en este archivo.
_AVISO_SIN_HERRAMIENTAS = (
    "En esta versión no tienes herramientas ni acceso al catálogo ni a los pedidos reales. "
    "Si te piden disponibilidad, precios o el estado de un pedido concreto, explica esa limitación "
    "y no inventes datos."
)
_AVISO_CON_HERRAMIENTAS = (
    "En esta versión dispones de dos herramientas y debes usarlas antes de afirmar datos:\n"
    "- consultar_pedido(id_pedido, email): exige los dos datos. "
    "Usa exactamente el id y el email que escriba el usuario. No inventes un correo "
    "ni llames con el email vacío si el usuario ya lo ha dado.\n"
    "- buscar_eventos(ciudad, categoria): devuelve el catálogo, incluido el id del evento. "
    "No filtra por mes; el mes se deduce de la fecha.\n"
    "Orden obligatorio: si el mensaje trae un id de pedido, la primera llamada es consultar_pedido. "
    "El pedido solo devuelve identificadores de evento. Para saber ciudad, categoría y fecha, "
    "llama después a buscar_eventos y cruza esos identificadores con el campo id. "
    "Si alguno es un concierto en la ciudad preguntada, responde que sí e indica los otros "
    "conciertos de esa ciudad cuyo año y mes coincidan. No incluyas el evento del pedido "
    "ni conciertos de otro mes. Si el pedido no existe, el email no coincide o faltan datos, "
    "no busques eventos y no inventes ciudad, categoría ni fecha."
)


def _sanear_rutas(texto: str) -> str:
    absoluta = str(RAIZ_PROYECTO.resolve())
    for prefijo in (absoluta + "/", absoluta + "\\", absoluta):
        texto = texto.replace(prefijo, "")
    return texto


def cargar_herramientas() -> list:
    """Devuelve las herramientas locales. Leen data/ de esta rama."""
    return [buscar_eventos, consultar_pedido]


def construir_prompt_v4(politicas: str) -> str:
    """Reutiliza el prompt de V2 y añade el uso de herramientas, sin tocar ese archivo."""
    prompt = construir_prompt_sistema(politicas)
    if _AVISO_SIN_HERRAMIENTAS not in prompt:
        raise ErrorConfiguracion(
            "El prompt de V2 ya no contiene el aviso de ausencia de herramientas. "
            "No se ha reescrito el comportamiento a ciegas."
        )
    return prompt.replace(_AVISO_SIN_HERRAMIENTAS, _AVISO_CON_HERRAMIENTAS)


def crear_nodo_chatbot(modelo_con_herramientas, prompt_sistema: str):
    """Llama al modelo con las herramientas registradas y devuelve su AIMessage."""

    def chatbot(state: MessagesState) -> dict[str, list[AIMessage]]:
        # El prompt no se guarda en el historial; solo orienta cada llamada.
        mensajes = [SystemMessage(content=prompt_sistema), *state["messages"]]
        respuesta = modelo_con_herramientas.invoke(mensajes)
        if not isinstance(respuesta, AIMessage):
            respuesta = AIMessage(content=texto_de_mensaje(respuesta))
        return {"messages": [respuesta]}

    return chatbot


def enrutar_despues_del_chatbot(state: MessagesState) -> Literal["herramientas", "__end__"]:
    """Si el modelo pide una herramienta, se ejecuta; si no, el grafo termina."""
    ultimo = state["messages"][-1]
    if isinstance(ultimo, AIMessage) and ultimo.tool_calls:
        return NODO_HERRAMIENTAS
    return END


def compilar_grafo(modelo, prompt_sistema: str, herramientas: list) -> CompiledStateGraph:
    """START → chatbot, con ciclo chatbot → herramientas → chatbot, y salida a END."""
    modelo_con_herramientas = modelo.bind_tools(herramientas)
    grafo = StateGraph(MessagesState)
    grafo.add_node(NODO_CHATBOT, crear_nodo_chatbot(modelo_con_herramientas, prompt_sistema))
    grafo.add_node(NODO_HERRAMIENTAS, ToolNode(herramientas))
    grafo.add_edge(START, NODO_CHATBOT)
    grafo.add_conditional_edges(
        NODO_CHATBOT,
        enrutar_despues_del_chatbot,
        {NODO_HERRAMIENTAS: NODO_HERRAMIENTAS, END: END},
    )
    grafo.add_edge(NODO_HERRAMIENTAS, NODO_CHATBOT)
    return grafo.compile()


def _respuesta_final(mensajes: list[BaseMessage]) -> str:
    for mensaje in reversed(mensajes):
        if isinstance(mensaje, AIMessage) and not mensaje.tool_calls:
            return texto_de_mensaje(mensaje)
    return ""


def _usos_de_herramientas(mensajes: list[BaseMessage]) -> list[tuple[str, str, str]]:
    """Devuelve nombre, argumentos y resultado, en el orden en que se ejecutaron."""
    argumentos: dict[str, str] = {}
    for mensaje in mensajes:
        if isinstance(mensaje, AIMessage):
            for llamada in mensaje.tool_calls:
                argumentos[str(llamada.get("id", ""))] = str(llamada.get("args", {}))
    usos: list[tuple[str, str, str]] = []
    for mensaje in mensajes:
        if isinstance(mensaje, ToolMessage):
            usos.append(
                (
                    mensaje.name or "herramienta",
                    argumentos.get(mensaje.tool_call_id, ""),
                    _sanear_rutas(texto_de_mensaje(mensaje)),
                )
            )
    return usos


def ejecutar_consulta(
    graph: CompiledStateGraph,
    texto: str,
    *,
    limite_pasos: int = LIMITE_PASOS,
) -> tuple[list[BaseMessage], bool]:
    """Ejecuta la consulta. Si el límite se alcanza, devuelve lo ya producido."""
    mensajes: list[BaseMessage] = [HumanMessage(content=texto)]
    try:
        for evento in graph.stream(
            {"messages": mensajes},
            {"recursion_limit": limite_pasos},
            stream_mode="updates",
        ):
            for actualizacion in evento.values():
                mensajes.extend(actualizacion.get("messages", []))
        return mensajes, False
    except GraphRecursionError:
        return mensajes, True


def imprimir_demostracion(mensajes: list[BaseMessage], limite_alcanzado: bool) -> None:
    print(f"Pregunta del usuario: {CONSULTA_DEMO}")
    print()
    usos = _usos_de_herramientas(mensajes)
    if not usos:
        print("No se ha ejecutado ninguna herramienta.")
    else:
        print("Herramientas ejecutadas:")
        for numero, (nombre, argumentos, resultado) in enumerate(usos, start=1):
            print(f"{numero}. {nombre}")
            print(f"   Argumentos: {argumentos}")
            print(f"   Resultado: {resultado}")
        print()
        print("Herramientas utilizadas: " + ", ".join(nombre for nombre, _, _ in usos))
    print()
    if limite_alcanzado:
        print(MENSAJE_LIMITE)
        print()
    final = _respuesta_final(mensajes)
    print(f"Respuesta final: {final or 'El asistente no ha llegado a una respuesta final.'}")


def demostrar(graph: CompiledStateGraph) -> None:
    print("Demostración V4. Las herramientas leen los JSON reales; no se inventan pedidos.")
    print(f"Políticas cargadas desde: {ruta_visible(RUTA_POLITICAS)}")
    print("Herramientas cargadas desde: tools/")
    print()
    mensajes, limite_alcanzado = ejecutar_consulta(graph, CONSULTA_DEMO)
    imprimir_demostracion(mensajes, limite_alcanzado)


def main() -> int:
    api_key = ""
    modelo = "OPENAI_MODEL"
    try:
        api_key, modelo = leer_configuracion()
        politicas = leer_politicas()
        herramientas = cargar_herramientas()
        graph = compilar_grafo(
            crear_modelo(api_key, modelo),
            construir_prompt_v4(politicas),
            herramientas,
        )
        demostrar(graph)
    except ErrorConfiguracion as exc:
        print(f"No se puede iniciar V4.\n{_sanear_rutas(str(exc))}", file=sys.stderr)
        return 1
    except OpenAIError as exc:
        error = interpretar_error_api(exc, api_key=api_key, modelo=modelo)
        print(
            f"No se ha podido completar la demostración.\n{type(exc).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"No se ha podido completar la demostración.\n{type(exc).__name__}: {_sanear_rutas(str(exc))}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
