"""Comprueba las plantillas y la selección de versión sin llamar a Langfuse."""

from __future__ import annotations

import unittest
from pathlib import Path

from graphs.v2_chatbot import leer_politicas
from observability.prompts import (
    NOMBRE_PROMPT,
    seleccion_explicita,
    texto_version,
    tono_por_defecto,
)
from graphs.v2_chatbot import ErrorConfiguracion


class PlantillaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.politicas = leer_politicas()
        self.version_1 = texto_version(1, self.politicas)
        self.version_2 = texto_version(2, self.politicas)

    def test_las_dos_versiones_conservan_las_instrucciones_funcionales(self) -> None:
        for texto in (self.version_1, self.version_2):
            self.assertIn("{{marca}}", texto)
            self.assertIn("{{tono}}", texto)
            self.assertNotIn("{marca}", texto.replace("{{marca}}", ""))
            self.assertIn("consultar_pedido", texto)
            self.assertIn("buscar_eventos", texto)
            self.assertIn("No inventes", texto)
            self.assertIn("7 días naturales", texto)
            self.assertIn("reembolso", texto.lower())

    def test_la_version_2_anade_huecos_y_datos_confirmados(self) -> None:
        self.assertIn("profesional y formal", self.version_1)
        self.assertNotIn("reconócelo expresamente", self.version_1)
        self.assertIn("cercano y conversacional", self.version_2)
        self.assertIn("reconócelo expresamente", self.version_2)
        self.assertIn("datos confirmados", self.version_2)
        self.assertIn("No inventes eventos, pedidos, fechas, precios ni políticas.", self.version_2)
        self.assertNotEqual(self.version_1, self.version_2)

    def test_la_seleccion_no_acepta_otra_version(self) -> None:
        self.assertIsNone(seleccion_explicita(None).version)
        self.assertEqual(seleccion_explicita(None).modalidad, "production")
        self.assertEqual(seleccion_explicita(1).modalidad, "version-1")
        self.assertEqual(seleccion_explicita(2).modalidad, "version-2")
        with self.assertRaises(ErrorConfiguracion):
            seleccion_explicita(3)

    def test_el_tono_por_defecto_depende_de_la_version_remota(self) -> None:
        self.assertEqual(tono_por_defecto(1), "profesional y formal")
        self.assertEqual(tono_por_defecto(2), "cercano y conversacional")

    def test_el_codigo_no_mueve_etiquetas_ni_mete_langfuse_en_v4(self) -> None:
        prompts = Path("observability/prompts.py").read_text(encoding="utf-8")
        trazas = Path("observability/langfuse_tracing.py").read_text(encoding="utf-8")
        v4 = Path("graphs/v4_tools.py").read_text(encoding="utf-8")
        self.assertNotIn(".update_prompt(", prompts)
        self.assertNotIn(".update_prompt(", trazas)
        self.assertIn(NOMBRE_PROMPT, prompts)
        self.assertIn("propagate_attributes", trazas)
        self.assertNotIn("langfuse", v4.lower())


if __name__ == "__main__":
    unittest.main()
