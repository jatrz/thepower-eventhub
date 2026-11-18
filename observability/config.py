"""Comprueba la configuración de Langfuse sin mostrar secretos."""

from __future__ import annotations

import os

from graphs.v2_chatbot import cargar_entorno

_PLACEHOLDERS = frozenset(
    {
        "",
        "pon_aqui_tu_clave_publica",
        "pon_aqui_tu_clave_secreta",
        "pk-lf-pon_aqui_tu_clave_publica",
        "sk-lf-pon_aqui_tu_clave_secreta",
        "pk-lf-...",
        "sk-lf-...",
    }
)

USER_ID_DEMO = "usuario-demo-eventhub"
TAGS_TRAZA = ["eventhub", "langgraph", "observability"]
BASE_URL_DEFECTO = "https://cloud.langfuse.com"


def _valor(nombre: str) -> str:
    return os.getenv(nombre, "").strip()


def langfuse_esta_configurado() -> bool:
    """True solo si hay claves reales. No imprime sus valores."""
    cargar_entorno()
    public = _valor("LANGFUSE_PUBLIC_KEY")
    secret = _valor("LANGFUSE_SECRET_KEY")
    return public.lower() not in _PLACEHOLDERS and secret.lower() not in _PLACEHOLDERS


def preparar_entorno_langfuse() -> None:
    """Fija la URL por defecto sin pisar una ya exportada."""
    cargar_entorno()
    os.environ.setdefault("LANGFUSE_BASE_URL", BASE_URL_DEFECTO)
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "development")
