"""Pruebas locales de observabilidad. No llaman a Langfuse ni al modelo."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from graphs.v4_tools import ejecutar_consulta
from observability.config import langfuse_esta_configurado
from observability.langfuse_tracing import CONVERSACIONES, ocultar_emails


class _GrafoFalso:
    def __init__(self) -> None:
        self.config = None
        self.entrada = None

    def stream(self, entrada, config, stream_mode="updates"):
        self.entrada = entrada
        self.config = config
        yield {"chatbot": {"messages": [AIMessage(content="respuesta de prueba")]}}


class ConsultaConfigTests(unittest.TestCase):
    def test_sin_config_solo_lleva_el_limite(self) -> None:
        grafo = _GrafoFalso()
        mensajes, limite = ejecutar_consulta(grafo, "hola", limite_pasos=7)
        self.assertFalse(limite)
        self.assertEqual(grafo.config, {"recursion_limit": 7})
        self.assertEqual(mensajes[-1].content, "respuesta de prueba")

    def test_config_conserva_callbacks_y_thread_id(self) -> None:
        grafo = _GrafoFalso()
        marca = object()
        ejecutar_consulta(
            grafo,
            "hola",
            config={"callbacks": [marca], "configurable": {"thread_id": "s6-traza-01"}},
        )
        self.assertEqual(grafo.config["callbacks"], [marca])
        self.assertEqual(grafo.config["configurable"]["thread_id"], "s6-traza-01")
        self.assertEqual(grafo.config["recursion_limit"], 12)


class ConfiguracionTests(unittest.TestCase):
    def test_sin_claves_no_esta_configurado(self) -> None:
        entorno = {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}
        with patch.dict(os.environ, entorno, clear=False), patch("observability.config.cargar_entorno"):
            self.assertFalse(langfuse_esta_configurado())

    def test_ejemplo_no_cuenta_como_configurado(self) -> None:
        entorno = {
            "LANGFUSE_PUBLIC_KEY": "pk-lf-pon_aqui_tu_clave_publica",
            "LANGFUSE_SECRET_KEY": "sk-lf-pon_aqui_tu_clave_secreta",
        }
        with patch.dict(os.environ, entorno, clear=False), patch("observability.config.cargar_entorno"):
            self.assertFalse(langfuse_esta_configurado())


class ConversacionesTests(unittest.TestCase):
    def test_hay_diez_sesiones_distintas(self) -> None:
        sesiones = [session_id for session_id, _ in CONVERSACIONES]
        self.assertEqual(len(sesiones), 10)
        self.assertEqual(len(set(sesiones)), 10)
        self.assertIn("PED-1001", CONVERSACIONES[7][1])
        self.assertIn("Valencia", CONVERSACIONES[4][1])

    def test_la_salida_local_oculta_el_email(self) -> None:
        self.assertNotIn("@", ocultar_emails("escribe ana.ejemplo@correo-ficticio.test"))

    def test_v4_no_importa_langfuse(self) -> None:
        texto = Path("graphs/v4_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("langfuse", texto.lower())
