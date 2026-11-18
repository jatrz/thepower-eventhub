"""Comprueba el adaptador de LangSmith sin red, sin modelo y sin claves."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from observability.dataset import CASOS, CATEGORIAS, NOMBRE_DATASET
from observability.langsmith_eval import (
    clasificar_dataset_remoto,
    config_de_ejecucion,
    diagnostico_langsmith,
    ejemplos_desde_casos,
    feedback_herramientas,
    feedback_juez,
    filas_de_resultados,
    traza_de_herramienta,
)
RAIZ = Path(__file__).resolve().parents[1]


class CacheEntornoTests(unittest.TestCase):
    def test_cargar_entorno_hace_visible_el_trazado(self) -> None:
        from graphs.v2_chatbot import cargar_entorno
        from langsmith.utils import get_env_var, tracing_is_enabled

        entorno = {
            "LANGSMITH_TRACING": "false",
            "LANGSMITH_PROJECT": "thepower-eventhub",
        }
        with mock.patch.dict(os.environ, entorno, clear=False):
            get_env_var.cache_clear()
            self.assertFalse(tracing_is_enabled())
            os.environ["LANGSMITH_TRACING"] = "true"
            self.assertFalse(tracing_is_enabled())
            with mock.patch("graphs.v2_chatbot.load_dotenv"):
                cargar_entorno()
            self.assertTrue(tracing_is_enabled())
        get_env_var.cache_clear()


class ConfiguracionLangSmithTests(unittest.TestCase):
    def test_exige_las_tres_variables_y_rechaza_las_antiguas(self) -> None:
        self.assertEqual(
            diagnostico_langsmith({}),
            diagnostico_langsmith(
                {
                    "LANGSMITH_TRACING": "",
                    "LANGSMITH_API_KEY": "",
                    "LANGSMITH_PROJECT": "",
                }
            ),
        )
        self.assertTrue(diagnostico_langsmith({}))
        self.assertFalse(
            diagnostico_langsmith(
                {
                    "LANGSMITH_TRACING": "true",
                    "LANGSMITH_API_KEY": "lsv2_pt_real_no_se_muestra",
                    "LANGSMITH_PROJECT": "thepower-eventhub",
                }
            )
        )
        problemas = diagnostico_langsmith(
            {
                "LANGSMITH_TRACING": "True",
                "LANGSMITH_API_KEY": "pon_aqui_tu_api_key",
                "LANGSMITH_PROJECT": "thepower-eventhub",
                "LANGCHAIN_API_KEY": "no-debe-usarse",
            }
        )
        self.assertGreaterEqual(len(problemas), 3)
        self.assertFalse(any("no-debe-usarse" in problema for problema in problemas))

    def test_el_codigo_no_mete_callbacks_ni_cambia_el_prompt(self) -> None:
        fuente = (RAIZ / "observability" / "langsmith_eval.py").read_text(encoding="utf-8")
        self.assertNotIn("update_prompt(", fuente)
        self.assertNotIn("CallbackHandler(", fuente)
        self.assertNotIn("from langsmith.callbacks", fuente)
        self.assertNotIn("label=\"latest\"", fuente)
        self.assertNotIn("label='latest'", fuente)
        config = config_de_ejecucion(
            "s6-ls-v1-caso",
            1,
            marca="EventHub",
            tono="profesional y formal",
            caso_id="evt-valencia-conciertos",
        )
        self.assertNotIn("callbacks", config)
        self.assertEqual(config["metadata"]["prompt_version"], "1")
        self.assertEqual(config["metadata"]["prompt_modalidad"], "version-1")
        self.assertEqual(config["configurable"]["thread_id"], "s6-ls-v1-caso")


class DatasetLangSmithTests(unittest.TestCase):
    def test_mapea_los_doce_casos_sin_cambiar_el_texto(self) -> None:
        ejemplos = ejemplos_desde_casos()
        self.assertEqual(len(ejemplos), 12)
        self.assertEqual(NOMBRE_DATASET, "eventhub-12")
        for categoria in CATEGORIAS:
            self.assertEqual(
                sum(ejemplo["metadata"]["categoria"] == categoria for ejemplo in ejemplos),
                4,
            )
        por_id = {caso.id: caso for caso in CASOS}
        for ejemplo in ejemplos:
            caso = por_id[ejemplo["metadata"]["id"]]
            self.assertEqual(ejemplo["inputs"]["pregunta"], caso.pregunta)
            self.assertEqual(ejemplo["reference_outputs"]["respuesta"], caso.esperada)

    def test_no_duplica_un_dataset_que_ya_coincide(self) -> None:
        remotos = []
        for ejemplo in ejemplos_desde_casos():
            remotos.append(
                SimpleNamespace(
                    inputs=ejemplo["inputs"],
                    outputs=ejemplo["reference_outputs"],
                    metadata=ejemplo["metadata"],
                )
            )
        self.assertEqual(clasificar_dataset_remoto([]), "vacio")
        self.assertEqual(clasificar_dataset_remoto(remotos), "coincide")
        sobran = [*remotos, remotos[0]]
        self.assertEqual(clasificar_dataset_remoto(sobran), "distinto")
        alterado = remotos[:-1]
        self.assertEqual(clasificar_dataset_remoto(alterado), "distinto")


class PuntuacionLangSmithTests(unittest.TestCase):
    def test_el_evaluador_determinista_no_mira_el_texto(self) -> None:
        acierto = feedback_herramientas(
            {"respuesta": "no menciono la herramienta", "herramientas": ["buscar_eventos"]},
            {"herramientas_esperadas": ["buscar_eventos"], "herramientas_prohibidas": []},
        )
        self.assertEqual(acierto["score"], 1)
        fallo = feedback_herramientas(
            {
                "respuesta": "he consultado el pedido y buscado eventos",
                "herramientas": ["consultar_pedido", "buscar_eventos"],
            },
            {
                "herramientas_esperadas": ["consultar_pedido"],
                "herramientas_prohibidas": ["buscar_eventos"],
            },
        )
        self.assertEqual(fallo["score"], 0)
        self.assertIn("indebidas: buscar_eventos", fallo["comment"])
        error = feedback_herramientas(
            {"error": "TimeoutError", "herramientas": ["consultar_pedido"]},
            {"herramientas_esperadas": ["consultar_pedido"]},
        )
        self.assertEqual(error["score"], 0)

    def test_las_medias_salen_de_las_dos_puntuaciones(self) -> None:
        filas = filas_de_resultados(
            [
                {
                    "run": SimpleNamespace(outputs={"error": False}),
                    "evaluation_results": {
                        "results": [
                            SimpleNamespace(key="herramientas", score=1),
                            SimpleNamespace(key="juez", score=1),
                        ]
                    },
                },
                {
                    "run": SimpleNamespace(outputs={"error": True}),
                    "evaluation_results": {
                        "results": [
                            {"key": "herramientas", "score": 0},
                            {"key": "juez", "score": 0},
                        ]
                    },
                },
            ]
        )
        self.assertEqual(len(filas), 2)
        from observability.evaluacion import calcular_metricas

        metricas = calcular_metricas(filas)
        self.assertEqual(metricas["casos"], 2)
        self.assertAlmostEqual(metricas["media_determinista"], 0.5)
        self.assertAlmostEqual(metricas["media_juez"], 0.5)
        self.assertEqual(metricas["errores"], 1)

    def test_sin_respuesta_el_juez_no_fuerza_un_acierto(self) -> None:
        convertido = feedback_juez("pregunta", "esperada", {"respuesta": ""})
        self.assertEqual(convertido["score"], 0)
        self.assertNotIn("correcta", convertido["comment"].lower())


class TrazaLocalTests(unittest.TestCase):
    def test_exige_la_sesion_y_la_herramienta_real(self) -> None:
        raiz = SimpleNamespace(
            id="raiz-1",
            trace_id="traza-1",
            name="eventhub-v4-langsmith",
            extra={"metadata": {"session_id": "s6-ls-demo", "dataset_caso": "evt-valencia-conciertos"}},
        )
        herramienta = SimpleNamespace(
            id="tool-1",
            trace_id="traza-1",
            name="buscar_eventos",
            extra={"metadata": {}},
        )
        self.assertIsNone(traza_de_herramienta([raiz], session_id="s6-ls-demo"))
        confirmada = traza_de_herramienta([raiz, herramienta], session_id="s6-ls-demo")
        self.assertEqual(confirmada["run_id"], "raiz-1")
        self.assertEqual(confirmada["herramienta"], "buscar_eventos")
        self.assertIsNone(traza_de_herramienta([raiz, herramienta], session_id="otra"))
