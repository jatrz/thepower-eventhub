"""Comprueba el dataset y los evaluadores sin llamar a Langfuse ni al modelo."""

from __future__ import annotations

import unittest
from pathlib import Path

from observability.dataset import CASOS, CATEGORIAS, NOMBRE_DATASET, validar_casos_locales
from observability.evaluacion import (
    Juicio,
    calcular_metricas,
    como_lista,
    puntuar_herramientas,
    puntuacion_de_juicio,
    recomendar,
)


class DatasetLocalTests(unittest.TestCase):
    def test_hay_doce_casos_y_cuatro_por_categoria(self) -> None:
        self.assertEqual(len(CASOS), 12)
        self.assertEqual(len({caso.id for caso in CASOS}), 12)
        for categoria in CATEGORIAS:
            self.assertEqual(sum(caso.categoria == categoria for caso in CASOS), 4)
        self.assertEqual(NOMBRE_DATASET, "eventhub-12")

    def test_las_respuestas_esperadas_salen_de_los_datos_reales(self) -> None:
        validar_casos_locales()

    def test_las_politicas_no_exigen_herramienta_y_el_pedido_doble_si(self) -> None:
        por_id = {caso.id: caso for caso in CASOS}
        for caso in CASOS:
            if caso.categoria == "politica":
                self.assertEqual(caso.herramientas_esperadas, ())
        self.assertEqual(
            por_id["ped-1004-conciertos-junio"].herramientas_esperadas,
            ("consultar_pedido", "buscar_eventos"),
        )
        self.assertEqual(
            por_id["ped-1004-email-incorrecto"].herramientas_prohibidas,
            ("buscar_eventos",),
        )


class EvaluadorDeterministaTests(unittest.TestCase):
    def test_acierta_falla_y_no_exige_herramienta_en_politicas(self) -> None:
        valor, comentario = puntuar_herramientas(
            ["consultar_pedido", "buscar_eventos"],
            ["consultar_pedido", "buscar_eventos"],
            [],
        )
        self.assertEqual(valor, 1)
        self.assertIn("usadas: consultar_pedido, buscar_eventos", comentario)

        valor, _ = puntuar_herramientas(["consultar_pedido"], ["consultar_pedido", "buscar_eventos"], [])
        self.assertEqual(valor, 0)

        valor, _ = puntuar_herramientas([], [], [])
        self.assertEqual(valor, 1)

        valor, comentario = puntuar_herramientas(
            ["consultar_pedido", "buscar_eventos"],
            ["consultar_pedido"],
            ["buscar_eventos"],
        )
        self.assertEqual(valor, 0)
        self.assertIn("indebidas: buscar_eventos", comentario)
        self.assertEqual(como_lista("buscar_eventos, consultar_pedido"), ["buscar_eventos", "consultar_pedido"])

    def test_las_medias_no_rellenan_huecos(self) -> None:
        metricas = calcular_metricas(
            [
                {"determinista": 1, "juez": 1},
                {"determinista": 0, "juez": 0},
                {"determinista": 1, "juez": 0, "error_ejecucion": True},
            ]
        )
        self.assertEqual(metricas["casos"], 3)
        self.assertAlmostEqual(metricas["media_determinista"], 2 / 3)
        self.assertAlmostEqual(metricas["media_juez"], 1 / 3)
        self.assertAlmostEqual(metricas["respuestas_correctas_pct"], 100 / 3)
        self.assertEqual(metricas["errores"], 2)
        self.assertEqual(metricas["herramientas_incorrectas"], 1)
        self.assertEqual(
            recomendar(
                {"media_juez": 0.5, "media_determinista": 1},
                {"media_juez": 0.5, "media_determinista": 0.5},
            ),
            "v1",
        )
        self.assertEqual(
            recomendar(
                {"media_juez": 0.4, "media_determinista": 1},
                {"media_juez": 0.4, "media_determinista": 1},
            ),
            "empate-mantener-v1",
        )

    def test_el_juicio_estructurado_no_fuerza_un_positivo(self) -> None:
        valor, razon = puntuacion_de_juicio(Juicio(razonamiento="Falta el plazo.", correcta=False))
        self.assertEqual(valor, 0)
        self.assertIn("Falta el plazo", razon)
        valor, _ = puntuacion_de_juicio(Juicio(razonamiento="Cubre los hechos.", correcta=True))
        self.assertEqual(valor, 1)
        valor, comentario = puntuacion_de_juicio(Juicio(razonamiento="  ", correcta=True))
        self.assertEqual(valor, 0)
        self.assertIn("No se fuerza", comentario)

    def test_el_modulo_no_mueve_etiquetas_ni_toca_v4(self) -> None:
        evaluacion = Path("observability/evaluacion.py").read_text(encoding="utf-8")
        dataset = Path("observability/dataset.py").read_text(encoding="utf-8")
        v4 = Path("graphs/v4_tools.py").read_text(encoding="utf-8")
        self.assertNotIn(".update_prompt(", evaluacion)
        self.assertNotIn(".update_prompt(", dataset)
        self.assertNotIn("langfuse", v4.lower())
        self.assertIn("version-", evaluacion)
        self.assertNotIn('label="latest"', evaluacion)
