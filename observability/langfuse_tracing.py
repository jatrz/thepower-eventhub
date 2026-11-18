"""Trazas de Langfuse para el grafo V4, sin cambiar su lógica de negocio.

Ejecutar desde la raíz, con las claves ya escritas en .env:

    python -m observability.langfuse_tracing

Si faltan las claves, termina sin llamar al modelo ni a Langfuse.
"""

from __future__ import annotations

import re
import sys

from langchain_core.messages import BaseMessage
from langgraph.graph.state import CompiledStateGraph
from openai import OpenAIError

from graphs.v2_chatbot import (
    ErrorConfiguracion,
    interpretar_error_api,
    leer_configuracion,
)
from graphs.v4_tools import (
    _respuesta_final,
    _sanear_rutas,
    _usos_de_herramientas,
    ejecutar_consulta,
)
from observability.config import (
    TAGS_TRAZA,
    USER_ID_DEMO,
    langfuse_esta_configurado,
    preparar_entorno_langfuse,
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Diez consultas reales del catálogo, las políticas y los pedidos de data/.
CONVERSACIONES: tuple[tuple[str, str], ...] = (
    ("s6-traza-01", "¿Cuál es la política de devolución de entradas?"),
    ("s6-traza-02", "Si EventHub o el organizador cancela un evento, ¿qué puede elegir el comprador?"),
    ("s6-traza-03", "¿Con cuánta antelación se puede cambiar la fecha o el evento de una entrada?"),
    ("s6-traza-04", "¿En qué plazo se abona un reembolso aprobado y a qué método de pago?"),
    ("s6-traza-05", "¿Qué conciertos hay en Valencia?"),
    ("s6-traza-06", "¿Qué eventos de cultura hay en Madrid?"),
    ("s6-traza-07", "¿Cuál es el concierto más barato en Madrid?"),
    (
        "s6-traza-08",
        "Consulta el pedido PED-1001 con el email ana.ejemplo@correo-ficticio.test.",
    ),
    (
        "s6-traza-09",
        "Consulta el pedido PED-1004 con el email incorrecto@example.com.",
    ),
    (
        "s6-traza-10",
        "Mi pedido es PED-1004 y el email es demo.madrid@correo-ficticio.test. "
        "¿Es para un concierto en Madrid? Si es así, dime otros conciertos en Madrid ese mes.",
    ),
)


def ocultar_emails(texto: str) -> str:
    """Oculta correos en la salida local. La traza remota sí recibe la pregunta original."""
    return _EMAIL.sub("[email-oculto]", texto)


def ejecutar_consulta_trazada(
    graph: CompiledStateGraph,
    texto: str,
    *,
    session_id: str,
    user_id: str = USER_ID_DEMO,
    prompt_cliente=None,
    modalidad: str = "production",
    marca: str = "",
    tono: str = "",
) -> tuple[list[BaseMessage], bool, str | None]:
    """Ejecuta V4 con CallbackHandler. El session_id no es un correo.

    Si llega el cliente de prompt de Langfuse 5, se enlaza con
    ``propagate_attributes(prompt=...)`` y con el metadato ``langfuse_prompt``
    que lee ``CallbackHandler``. No cambia etiquetas del prompt.
    """
    from langfuse import get_client, propagate_attributes
    from langfuse.langchain import CallbackHandler

    handler = CallbackHandler()
    metadatos = {
        "grafo": "v4",
        "herramientas": "buscar_eventos,consultar_pedido",
        "prompt_modalidad": modalidad,
    }
    config: dict = {
        "callbacks": [handler],
        "run_name": "eventhub-v4",
        "configurable": {"thread_id": session_id},
    }
    if prompt_cliente is not None:
        metadatos.update(
            {
                "prompt_nombre": prompt_cliente.name,
                "prompt_version": str(prompt_cliente.version),
                "marca": marca,
                "tono": tono,
            }
        )
        config["metadata"] = {
            "langfuse_prompt": prompt_cliente,
            "prompt_nombre": prompt_cliente.name,
            "prompt_version": str(prompt_cliente.version),
            "prompt_modalidad": modalidad,
        }
    etiquetas = list(TAGS_TRAZA) + [f"modalidad-{modalidad}"]
    if prompt_cliente is not None:
        etiquetas.append(f"prompt-v{prompt_cliente.version}")
    with propagate_attributes(
        trace_name="eventhub-v4",
        user_id=user_id,
        session_id=session_id,
        tags=etiquetas,
        metadata=metadatos,
        prompt=prompt_cliente,
    ):
        mensajes, limite = ejecutar_consulta(graph, texto, config=config)
    get_client().flush()
    return mensajes, limite, handler.last_trace_id


def _resumen(mensajes: list[BaseMessage], limite: bool) -> str:
    usos = _usos_de_herramientas(mensajes)
    nombres = ", ".join(nombre for nombre, _, _ in usos) or "ninguna"
    final = _respuesta_final(mensajes)
    estado = "con respuesta final" if final else "sin respuesta final"
    if limite:
        estado += "; límite de pasos alcanzado"
    return f"herramientas: {nombres}; {estado}"


def ejecutar_una(
    pregunta: str,
    *,
    version: int | None,
    session_id: str,
    marca: str | None = None,
    tono: str | None = None,
) -> dict[str, object]:
    """Ejecuta una pregunta con production o con una versión explícita.

    No cambia la etiqueta production. Sirve para comparar la versión 1 y la 2
    sin alterar el funcionamiento normal.
    """
    from observability.prompts import seleccionar_y_compilar

    graph, prompt, marca_final, tono_final = seleccionar_y_compilar(
        version,
        marca=marca,
        tono=tono,
    )
    modalidad = "production" if version is None else f"version-{version}"
    mensajes, limite, trace_id = ejecutar_consulta_trazada(
        graph,
        pregunta,
        session_id=session_id,
        prompt_cliente=prompt,
        modalidad=modalidad,
        marca=marca_final,
        tono=tono_final,
    )
    return {
        "mensajes": mensajes,
        "limite": limite,
        "trace_id": trace_id,
        "prompt_nombre": prompt.name,
        "prompt_version": prompt.version,
        "prompt_etiquetas": list(prompt.labels),
        "modalidad": modalidad,
        "marca": marca_final,
        "tono": tono_final,
        "respuesta": _respuesta_final(mensajes),
        "pregunta": pregunta,
    }


def _argumento_version(argv: list[str]) -> int | None:
    if "--version" not in argv:
        return None
    indice = argv.index("--version")
    if indice + 1 >= len(argv):
        raise ErrorConfiguracion("Falta el número después de --version.")
    bruto = argv[indice + 1]
    if bruto not in {"1", "2"}:
        raise ErrorConfiguracion("--version solo admite 1 o 2. No mueve la etiqueta production.")
    return int(bruto)


def main(argv: list[str] | None = None) -> int:
    if not langfuse_esta_configurado():
        print(
            "Langfuse no está configurado. "
            "Faltan LANGFUSE_PUBLIC_KEY o LANGFUSE_SECRET_KEY en .env, o siguen siendo el ejemplo."
        )
        print("No se ha llamado al modelo ni se ha enviado ninguna traza.")
        print("V4 sin observabilidad sigue disponible: python -m graphs.v4_tools")
        return 2

    preparar_entorno_langfuse()
    try:
        from langfuse import get_client
    except ImportError:
        print("No se encuentra el paquete langfuse. Instala requirements.txt. No se muestra ninguna clave.")
        return 2

    if not get_client().auth_check():
        print("Langfuse ha rechazado las credenciales. No se muestra ninguna clave.")
        return 2

    argumentos = list(sys.argv[1:] if argv is None else argv)
    if "--pregunta" in argumentos or "--version" in argumentos or "--production" in argumentos:
        return _main_una(argumentos)

    api_key = ""
    modelo = "OPENAI_MODEL"
    try:
        from observability.prompts import (
            MARCA_DEFECTO,
            seleccionar_y_compilar,
        )

        api_key, modelo = leer_configuracion()
        graph, prompt, marca, tono = seleccionar_y_compilar(
            None,
            marca=MARCA_DEFECTO,
            tono=None,
        )
        print(f"Prompt: {prompt.name} versión {prompt.version} modalidad production")
        print(f"Conversaciones de prueba: {len(CONVERSACIONES)}")
        print(f"user_id: {USER_ID_DEMO}")
        print("Cada sesión usa su propio session_id. No se reutiliza el historial de otra.")
        for session_id, pregunta in CONVERSACIONES:
            mensajes, limite, trace_id = ejecutar_consulta_trazada(
                graph,
                pregunta,
                session_id=session_id,
                prompt_cliente=prompt,
                modalidad="production",
                marca=marca,
                tono=tono,
            )
            print(f"{session_id}: {_resumen(mensajes, limite)}")
            print(f"  pregunta: {ocultar_emails(pregunta)}")
            print(f"  traza: {trace_id or 'sin id'} prompt v{prompt.version}")
    except ErrorConfiguracion as exc:
        print(f"No se puede iniciar la traza.\n{_sanear_rutas(str(exc))}", file=sys.stderr)
        return 1
    except OpenAIError as exc:
        error = interpretar_error_api(exc, api_key=api_key, modelo=modelo)
        print(
            f"No se ha podido completar la traza.\n{type(exc).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"No se ha podido completar la traza.\n{type(exc).__name__}: {_sanear_rutas(str(exc))}",
            file=sys.stderr,
        )
        return 1

    print()
    print("Se ha pedido a Langfuse que reciba las trazas. Este script no consulta la interfaz.")
    print("No se han leído tokens, costes ni duraciones. Si el proveedor no los envía, Langfuse no los tendrá.")
    return 0


def _main_una(argumentos: list[str]) -> int:
    if "--pregunta" not in argumentos:
        print("Hace falta --pregunta para ejecutar una versión concreta.", file=sys.stderr)
        return 2
    indice = argumentos.index("--pregunta")
    if indice + 1 >= len(argumentos):
        print("Falta el texto después de --pregunta.", file=sys.stderr)
        return 2
    pregunta = argumentos[indice + 1]
    if "--version" in argumentos and "--production" in argumentos:
        print("Elige --version o --production, no los dos. No se mueve ninguna etiqueta.", file=sys.stderr)
        return 2
    try:
        version = _argumento_version(argumentos)
    except ErrorConfiguracion as exc:
        print(str(exc), file=sys.stderr)
        return 2
    session_id = "s6-prompt-production" if version is None else f"s6-prompt-v{version}"
    api_key = ""
    modelo = "OPENAI_MODEL"
    try:
        api_key, modelo = leer_configuracion()
        resultado = ejecutar_una(pregunta, version=version, session_id=session_id)
    except ErrorConfiguracion as exc:
        print(f"No se puede ejecutar el prompt.\n{_sanear_rutas(str(exc))}", file=sys.stderr)
        return 1
    except OpenAIError as exc:
        error = interpretar_error_api(exc, api_key=api_key, modelo=modelo)
        print(f"No se ha podido ejecutar el prompt.\n{type(exc).__name__}: {error}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"No se ha podido ejecutar el prompt.\n{type(exc).__name__}: {_sanear_rutas(str(exc))}",
            file=sys.stderr,
        )
        return 1
    print(f"prompt: {resultado['prompt_nombre']} versión {resultado['prompt_version']}")
    print(f"modalidad: {resultado['modalidad']}")
    print(f"etiquetas remotas: {', '.join(resultado['prompt_etiquetas'])}")
    print(f"traza: {resultado['trace_id'] or 'sin id'}")
    print(f"respuesta: {ocultar_emails(str(resultado['respuesta'])) or 'sin respuesta final'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
