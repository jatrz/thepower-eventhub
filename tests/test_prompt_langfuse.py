"""Pruebas reales contra Langfuse. No simulan el cliente.

Sin claves en .env, se omiten. La ejecución del grafo gasta una llamada al
modelo por modalidad y solo corre si EVENTHUB_PROMPT_EJECUTAR=1.
"""

from __future__ import annotations

import os
import time
import unittest
import uuid

from graphs.v2_chatbot import ErrorConfiguracion
from observability.config import langfuse_esta_configurado
from observability.prompts import (
    NOMBRE_PROMPT,
    comprobar_remoto,
    publicar_si_falta,
    recuperar_prompt,
    seleccion_explicita,
    texto_para_langchain,
    valores_de_plantilla,
)

_EJECUTAR_GRAFO = os.getenv("EVENTHUB_PROMPT_EJECUTAR", "").strip() == "1"
_PREGUNTA = "¿Hasta cuántos días antes del evento se puede devolver una entrada? Responde en una frase."


def _observaciones(trace_id: str):
    from langfuse import get_client

    return get_client().api.observations.get_many(
        trace_id=trace_id,
        fields="core,basic,io,metadata,prompt",
        limit=50,
    )


def _esperar_traza(trace_id: str, pregunta: str):
    ultimo = None
    for _ in range(12):
        ultimo = _observaciones(trace_id)
        textos = " ".join(str(getattr(item, "input", "") or "") for item in ultimo.data).lower()
        ligados = [
            item
            for item in ultimo.data
            if getattr(item, "prompt_name", None) == NOMBRE_PROMPT
        ]
        if ligados and pregunta.lower().split()[0] in textos:
            return ultimo
        time.sleep(3)
    return ultimo


@unittest.skipUnless(langfuse_esta_configurado(), "Hace falta Langfuse configurado en .env. No es un fallo del código.")
class PromptRemotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        publicar_si_falta()

    def test_recuperacion_sustitucion_y_langchain(self) -> None:
        resumen = comprobar_remoto()
        self.assertEqual(resumen["nombre"], NOMBRE_PROMPT)
        self.assertEqual(resumen["produccion"], 1)
        self.assertIn("production", resumen["etiquetas_v1"])
        self.assertNotIn("production", resumen["etiquetas_v2"])
        self.assertEqual(set(resumen["variables"]), {"marca", "tono"})

        for version in (None, 1, 2):
            prompt = recuperar_prompt(seleccion_explicita(version))
            marca, tono = valores_de_plantilla(prompt, marca="MarcaPrueba", tono="TonoPrueba")
            texto = texto_para_langchain(prompt, marca=marca, tono=tono)
            self.assertIn("MarcaPrueba", texto)
            self.assertIn("TonoPrueba", texto)
            self.assertNotIn("{{", texto)
            self.assertIn("consultar_pedido", texto)

    def test_la_version_2_no_cambia_production(self) -> None:
        recuperar_prompt(seleccion_explicita(2))
        produccion = recuperar_prompt(seleccion_explicita(None))
        self.assertEqual(produccion.version, 1)
        self.assertIn("production", produccion.labels)


@unittest.skipUnless(langfuse_esta_configurado(), "Hace falta Langfuse configurado en .env.")
@unittest.skipUnless(_EJECUTAR_GRAFO, "Define EVENTHUB_PROMPT_EJECUTAR=1 para llamar al modelo y crear trazas.")
class EjecucionGrafoTests(unittest.TestCase):
    def test_versiones_y_production_dejan_traza(self) -> None:
        from graphs.v4_tools import _respuesta_final
        from observability.langfuse_tracing import ejecutar_una

        casos = (
            (1, "version-1"),
            (2, "version-2"),
            (None, "production"),
        )
        for version, modalidad in casos:
            with self.subTest(modalidad=modalidad):
                session_id = f"s6-prompt-{modalidad}-{uuid.uuid4().hex[:8]}"
                try:
                    resultado = ejecutar_una(
                        _PREGUNTA,
                        version=version,
                        session_id=session_id,
                        marca="EventHub",
                        tono=None,
                    )
                except ErrorConfiguracion as exc:
                    self.fail(str(exc))
                self.assertEqual(resultado["prompt_nombre"], NOMBRE_PROMPT)
                self.assertEqual(resultado["modalidad"], modalidad)
                self.assertEqual(resultado["prompt_version"], 1 if version is None else version)
                self.assertTrue(_respuesta_final(resultado["mensajes"]))
                self.assertTrue(resultado["trace_id"])
                remoto = _esperar_traza(str(resultado["trace_id"]), _PREGUNTA)
                self.assertIsNotNone(remoto)
                self.assertTrue(remoto.data, "Langfuse no ha devuelto observaciones de la traza.")
                ligados = [
                    item
                    for item in remoto.data
                    if getattr(item, "prompt_name", None) == NOMBRE_PROMPT
                    and getattr(item, "prompt_version", None) == resultado["prompt_version"]
                ]
                metadatos = " ".join(str(getattr(item, "metadata", "") or "") for item in remoto.data)
                self.assertTrue(
                    ligados,
                    "Ninguna observación enlaza el nombre y la versión del prompt.",
                )
                entradas = " ".join(str(getattr(item, "input", "") or "") for item in remoto.data)
                salidas = " ".join(str(getattr(item, "output", "") or "") for item in remoto.data)
                self.assertIn(modalidad, metadatos)
                self.assertIn("devolver", entradas.lower())
                self.assertTrue(salidas.strip())


if __name__ == "__main__":
    unittest.main()
