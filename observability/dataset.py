"""Dataset eventhub-12, construido solo con datos reales del repositorio.

No inventa eventos, pedidos, correos, fechas, precios ni políticas. La
publicación en Langfuse es idempotente: si el dataset ya tiene estos 12 casos,
no crea otro ni duplica ítems.
"""

from __future__ import annotations

from dataclasses import dataclass

from graphs.v2_chatbot import ErrorConfiguracion, leer_politicas
from tools.events_tool import load_events
from tools.orders_tool import load_orders

NOMBRE_DATASET = "eventhub-12"
CATEGORIAS = ("politica", "evento", "pedido")


@dataclass(frozen=True)
class Caso:
    """Un caso del dataset. La herramienta esperada puede estar vacía."""

    id: str
    categoria: str
    pregunta: str
    esperada: str
    herramientas_esperadas: tuple[str, ...] = ()
    herramientas_prohibidas: tuple[str, ...] = ()

    def metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "categoria": self.categoria,
            "herramientas_esperadas": list(self.herramientas_esperadas),
            "herramientas_prohibidas": list(self.herramientas_prohibidas),
        }


CASOS: tuple[Caso, ...] = (
    Caso(
        id="pol-devolucion",
        categoria="politica",
        pregunta=(
            "¿Hasta cuándo puedo solicitar la devolución de una entrada "
            "y qué comisión retiene EventHub?"
        ),
        esperada=(
            "Se puede solicitar la devolución hasta 7 días naturales antes del evento. "
            "La entrada debe estar sin usar y el pedido debe figurar como confirmado. "
            "EventHub retiene una comisión de gestión de 2 EUR por entrada devuelta. "
            "No se aceptan devoluciones el mismo día del evento ni después de que haya empezado."
        ),
    ),
    Caso(
        id="pol-cancelacion-organizador",
        categoria="politica",
        pregunta="Si EventHub o el organizador cancela el evento, ¿qué opciones tiene el comprador?",
        esperada=(
            "El comprador puede elegir un reembolso íntegro o un bono por el mismo importe."
        ),
    ),
    Caso(
        id="pol-cambio",
        categoria="politica",
        pregunta=(
            "¿Puedo cambiar la fecha o el evento de una entrada "
            "y qué ocurre con la diferencia de precio?"
        ),
        esperada=(
            "Se puede cambiar la fecha o el evento una sola vez, siempre que queden "
            "al menos 72 horas para el evento original y el nuevo evento tenga "
            "disponibilidad suficiente. Si el nuevo evento cuesta más, el comprador "
            "abona la diferencia. Si cuesta menos, la diferencia se devuelve como bono "
            "de EventHub, no en efectivo. No se cambian entradas nominativas ya "
            "validadas en el acceso."
        ),
    ),
    Caso(
        id="pol-reembolso",
        categoria="politica",
        pregunta=(
            "Si me aprueban un reembolso, ¿en qué plazo lo recibo, "
            "a qué método de pago y qué importe se devuelve?"
        ),
        esperada=(
            "Los reembolsos aprobados se emiten al mismo método de pago usado en la compra. "
            "El plazo de abono es de 5 a 10 días hábiles desde la aprobación. "
            "El importe reembolsable es el precio de la entrada menos la comisión de gestión, "
            "salvo cancelación del evento por parte del organizador. "
            "Un pedido en estado reembolsado no admite un segundo reembolso sobre las mismas entradas."
        ),
    ),
    Caso(
        id="evt-valencia-conciertos",
        categoria="evento",
        pregunta=(
            "¿Qué conciertos hay en Valencia en el catálogo? "
            "Indica el nombre, la fecha, el precio y la disponibilidad de cada uno."
        ),
        esperada=(
            "En Valencia hay cinco conciertos: "
            "Noche Indie en la Marina (EVT-001), 2026-06-12, 28 EUR, 180 plazas; "
            "Valencia Jazz al Atardecer (EVT-002), 2026-07-03, 35 EUR, 95 plazas; "
            "Electro Beach Festival (EVT-003), 2026-08-15, 55 EUR, 420 plazas; "
            "Clásicos en el Palau (EVT-004), 2026-09-20, 42 EUR, 60 plazas; "
            "Rock en la Ribera (EVT-005), 2026-10-04, 22 EUR, 248 plazas. "
            "No hay más conciertos en Valencia en el catálogo."
        ),
        herramientas_esperadas=("buscar_eventos",),
    ),
    Caso(
        id="evt-madrid-cultura",
        categoria="evento",
        pregunta="¿Hay eventos de cultura en Madrid? Dime el nombre, la fecha y el precio.",
        esperada=(
            "Sí. El único evento de cultura en Madrid es la Feria del Libro de Otoño "
            "(EVT-006), el 2026-10-18, a 8 EUR."
        ),
        herramientas_esperadas=("buscar_eventos",),
    ),
    Caso(
        id="evt-madrid-barato",
        categoria="evento",
        pregunta=(
            "¿Cuál es el concierto más barato en Madrid según el catálogo? "
            "Indica nombre, fecha y precio."
        ),
        esperada=(
            "El concierto más barato en Madrid es Rock en La Latina (EVT-011), "
            "el 2026-06-27, a 26 EUR. "
            "La Feria del Libro de Otoño cuesta 8 EUR, pero es de cultura, no un concierto."
        ),
        herramientas_esperadas=("buscar_eventos",),
    ),
    Caso(
        id="evt-bilbao",
        categoria="evento",
        pregunta="¿Qué conciertos hay en Bilbao en el catálogo?",
        esperada=(
            "No hay conciertos en Bilbao en el catálogo de EventHub. "
            "No debe inventarse ningún evento, fecha ni precio."
        ),
        herramientas_esperadas=("buscar_eventos",),
    ),
    Caso(
        id="ped-1001-confirmado",
        categoria="pedido",
        pregunta=(
            "¿Cuál es el estado del pedido PED-1001? "
            "El email es ana.ejemplo@correo-ficticio.test."
        ),
        esperada=(
            "El pedido PED-1001 está confirmado. "
            "Incluye los eventos EVT-001 y EVT-003, y la cantidad es 2."
        ),
        herramientas_esperadas=("consultar_pedido",),
    ),
    Caso(
        id="ped-1003-cancelado",
        categoria="pedido",
        pregunta=(
            "Quiero saber el estado del pedido PED-1003. "
            "Mi correo es marta.demo@correo-ficticio.test."
        ),
        esperada=(
            "El pedido PED-1003 está cancelado. El evento es EVT-008 y la cantidad es 3."
        ),
        herramientas_esperadas=("consultar_pedido",),
    ),
    Caso(
        id="ped-1004-email-incorrecto",
        categoria="pedido",
        pregunta="Consulta el pedido PED-1004 con el email ana.ejemplo@correo-ficticio.test.",
        esperada=(
            "El email no coincide con el pedido PED-1004. "
            "No se puede mostrar el estado, los eventos, la cantidad ni el email registrado."
        ),
        herramientas_esperadas=("consultar_pedido",),
        herramientas_prohibidas=("buscar_eventos",),
    ),
    Caso(
        id="ped-1004-conciertos-junio",
        categoria="pedido",
        pregunta=(
            "Mi pedido es PED-1004 y el email es demo.madrid@correo-ficticio.test. "
            "¿Es para un concierto en Madrid? Si es así, dime otros conciertos en Madrid ese mes."
        ),
        esperada=(
            "Sí. El pedido PED-1004 está confirmado, la cantidad es 1 y el evento es EVT-009, "
            "Noche Indie en Malasaña, un concierto en Madrid el 2026-06-12. "
            "Otros conciertos en Madrid en junio de 2026, sin incluir el del pedido, son "
            "Jazz en el Retiro (EVT-010), el 2026-06-21, a 34 EUR, "
            "y Rock en La Latina (EVT-011), el 2026-06-27, a 26 EUR. "
            "No incluye Clásicos en el Auditorio, que es del 2026-07-18."
        ),
        herramientas_esperadas=("consultar_pedido", "buscar_eventos"),
    ),
)


def validar_casos_locales() -> None:
    """Falla si los 12 casos no cuadran con políticas, eventos y pedidos reales."""
    if len(CASOS) != 12:
        raise ErrorConfiguracion(f"eventhub-12 debe tener 12 casos, no {len(CASOS)}.")
    identificadores = [caso.id for caso in CASOS]
    if len(set(identificadores)) != 12:
        raise ErrorConfiguracion("Hay identificadores de caso repetidos.")
    for categoria in CATEGORIAS:
        cantidad = sum(caso.categoria == categoria for caso in CASOS)
        if cantidad != 4:
            raise ErrorConfiguracion(
                f"La categoría {categoria} tiene {cantidad} casos; deben ser 4."
            )

    politicas = leer_politicas()
    for fragmento in (
        "7 días naturales",
        "2 EUR",
        "reembolso íntegro o un bono",
        "72 horas",
        "no en efectivo",
        "5 a 10 días hábiles",
        "mismo método de pago",
    ):
        if fragmento not in politicas:
            raise ErrorConfiguracion(
                f"data/policies.md ya no contiene «{fragmento}». No se publica una respuesta desfasada."
            )
    for caso in CASOS:
        if caso.categoria != "politica":
            continue
        for fragmento in _fragmentos_politica(caso.id):
            if fragmento not in caso.esperada or fragmento not in politicas:
                raise ErrorConfiguracion(
                    f"{caso.id} no conserva el texto real de las políticas: {fragmento}."
                )

    eventos = [evento for evento in load_events() if isinstance(evento, dict)]
    _exigir_eventos(
        "evt-valencia-conciertos",
        [
            evento
            for evento in eventos
            if evento.get("ciudad") == "Valencia" and evento.get("categoria") == "concierto"
        ],
        5,
    )
    _exigir_eventos(
        "evt-madrid-cultura",
        [
            evento
            for evento in eventos
            if evento.get("ciudad") == "Madrid" and evento.get("categoria") == "cultura"
        ],
        1,
    )
    if any(evento.get("ciudad") == "Bilbao" for evento in eventos):
        raise ErrorConfiguracion("El catálogo ahora tiene eventos en Bilbao. Revisa evt-bilbao.")
    bilbao = _caso("evt-bilbao")
    if "No hay conciertos en Bilbao" not in bilbao.esperada:
        raise ErrorConfiguracion("evt-bilbao ya no dice que no hay conciertos.")

    madrid = [
        evento
        for evento in eventos
        if evento.get("ciudad") == "Madrid" and evento.get("categoria") == "concierto"
    ]
    mas_barato = min(madrid, key=lambda evento: float(evento["precio"]))
    if mas_barato.get("id") != "EVT-011" or float(mas_barato["precio"]) != 26.0:
        raise ErrorConfiguracion(
            "El concierto más barato de Madrid ya no es EVT-011 a 26 EUR. No se publica el caso."
        )
    if "Rock en La Latina" not in _caso("evt-madrid-barato").esperada:
        raise ErrorConfiguracion("evt-madrid-barato no nombra el concierto real más barato.")

    junio = [
        evento
        for evento in madrid
        if str(evento.get("fecha", "")).startswith("2026-06") and evento.get("id") != "EVT-009"
    ]
    nombres_junio = {evento.get("nombre") for evento in junio}
    if nombres_junio != {"Jazz en el Retiro", "Rock en La Latina"}:
        raise ErrorConfiguracion(
            "Los otros conciertos de Madrid en junio de 2026 han cambiado. Revisa el caso del pedido."
        )
    pedido_junio = _caso("ped-1004-conciertos-junio").esperada
    for nombre in nombres_junio:
        if nombre not in pedido_junio:
            raise ErrorConfiguracion(f"La respuesta esperada omite {nombre}.")
    if "2026-07-18" not in pedido_junio:
        raise ErrorConfiguracion("Falta la fecha real que excluye Clásicos en el Auditorio.")

    pedidos = {pedido.get("id_pedido"): pedido for pedido in load_orders() if isinstance(pedido, dict)}
    _exigir_pedido("ped-1001-confirmado", pedidos, "PED-1001", "confirmado", ["EVT-001", "EVT-003"], 2)
    _exigir_pedido("ped-1003-cancelado", pedidos, "PED-1003", "cancelado", ["EVT-008"], 3)
    pedido_1004 = pedidos.get("PED-1004")
    if not pedido_1004 or pedido_1004.get("email") != "demo.madrid@correo-ficticio.test":
        raise ErrorConfiguracion("PED-1004 ya no tiene el email real usado en el dataset.")
    incorrecto = _caso("ped-1004-email-incorrecto").esperada.casefold()
    if "no coincide" not in incorrecto:
        raise ErrorConfiguracion("El caso de email incorrecto no exige rechazar la consulta.")
    for prohibido in ("evt-009", "demo.madrid@", "confirmado"):
        if prohibido in incorrecto:
            raise ErrorConfiguracion(
                "La respuesta esperada del email incorrecto revela datos del pedido."
            )


def publicar_dataset() -> str:
    """Crea eventhub-12 si no existe. No modifica un dataset distinto."""
    from observability.config import langfuse_esta_configurado, preparar_entorno_langfuse

    validar_casos_locales()
    if not langfuse_esta_configurado():
        raise ErrorConfiguracion(
            "Langfuse no está configurado. No se publica el dataset y no se muestran las claves."
        )
    preparar_entorno_langfuse()
    from langfuse import get_client

    cliente = get_client()
    if not cliente.auth_check():
        raise ErrorConfiguracion("Langfuse ha rechazado las credenciales. No se muestra ninguna clave.")

    remoto = _buscar_dataset(cliente)
    if remoto is None:
        cliente.create_dataset(
            name=NOMBRE_DATASET,
            description=(
                "12 casos reales de EventHub: 4 políticas, 4 eventos y 4 pedidos. "
                "Las respuestas esperadas salen de data/policies.md, data/events.json y data/orders.json."
            ),
            metadata={"origen": "thepower-eventhub", "casos": 12},
        )
        for caso in CASOS:
            cliente.create_dataset_item(
                dataset_name=NOMBRE_DATASET,
                id=caso.id,
                input=caso.pregunta,
                expected_output=caso.esperada,
                metadata=caso.metadata(),
            )
        remoto = _buscar_dataset(cliente)
        if remoto is None:
            raise ErrorConfiguracion("Langfuse no ha devuelto el dataset recién creado.")
        _coinciden(remoto)
        return "creado"

    _coinciden(remoto)
    return "ya-existia"


def _caso(identificador: str) -> Caso:
    for caso in CASOS:
        if caso.id == identificador:
            return caso
    raise ErrorConfiguracion(f"No existe el caso {identificador}.")


def _fragmentos_politica(identificador: str) -> tuple[str, ...]:
    return {
        "pol-devolucion": ("7 días naturales", "2 EUR", "sin usar"),
        "pol-cancelacion-organizador": ("reembolso íntegro", "bono"),
        "pol-cambio": ("72 horas", "no en efectivo", "nominativas"),
        "pol-reembolso": ("5 a 10 días hábiles", "mismo método de pago", "reembolsado"),
    }[identificador]


def _exigir_eventos(identificador: str, encontrados: list[dict], cantidad: int) -> None:
    if len(encontrados) != cantidad:
        raise ErrorConfiguracion(
            f"{identificador} esperaba {cantidad} eventos reales y hay {len(encontrados)}."
        )
    esperada = _caso(identificador).esperada
    for evento in encontrados:
        for campo in ("id", "nombre", "fecha"):
            if str(evento.get(campo, "")) not in esperada:
                raise ErrorConfiguracion(
                    f"{identificador} no incluye el {campo} real {evento.get(campo)}."
                )
        precio = evento.get("precio")
        if precio is None or str(int(precio)) not in esperada:
            raise ErrorConfiguracion(f"{identificador} no incluye el precio real {precio}.")


def _exigir_pedido(
    identificador: str,
    pedidos: dict,
    id_pedido: str,
    estado: str,
    eventos: list[str],
    cantidad: int,
) -> None:
    pedido = pedidos.get(id_pedido)
    if not pedido:
        raise ErrorConfiguracion(f"No existe el pedido real {id_pedido}.")
    if pedido.get("estado") != estado or pedido.get("eventos") != eventos or pedido.get("cantidad") != cantidad:
        raise ErrorConfiguracion(f"{id_pedido} ya no coincide con la respuesta esperada de {identificador}.")
    esperada = _caso(identificador).esperada
    if id_pedido not in esperada or estado not in esperada or str(cantidad) not in esperada:
        raise ErrorConfiguracion(f"{identificador} no repite los datos reales del pedido.")
    for evento in eventos:
        if evento not in esperada:
            raise ErrorConfiguracion(f"{identificador} omite el evento real {evento}.")


def _buscar_dataset(cliente):
    from langfuse.api import NotFoundError

    try:
        return cliente.get_dataset(NOMBRE_DATASET, fetch_items_page_size=50)
    except NotFoundError:
        return None
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError":
            return None
        raise ErrorConfiguracion(
            "No se ha podido leer el dataset. No se muestran las claves."
        ) from exc


def _coinciden(dataset) -> None:
    items = list(dataset.items)
    if len(items) != 12:
        raise ErrorConfiguracion(
            f"{NOMBRE_DATASET} ya existe con {len(items)} ítems. No se duplica ni se reescribe."
        )
    remotos = {item.id: item for item in items}
    if set(remotos) != {caso.id for caso in CASOS}:
        raise ErrorConfiguracion(
            f"{NOMBRE_DATASET} ya existe con otros identificadores. No se reescribe."
        )
    for caso in CASOS:
        item = remotos[caso.id]
        metadata = item.metadata or {}
        if item.input != caso.pregunta or item.expected_output != caso.esperada:
            raise ErrorConfiguracion(
                f"El ítem {caso.id} remoto no coincide con el repositorio. No se reescribe."
            )
        if metadata.get("categoria") != caso.categoria:
            raise ErrorConfiguracion(f"La categoría remota de {caso.id} no coincide.")
        if list(metadata.get("herramientas_esperadas") or []) != list(caso.herramientas_esperadas):
            raise ErrorConfiguracion(f"Las herramientas esperadas de {caso.id} no coinciden.")
        if list(metadata.get("herramientas_prohibidas") or []) != list(caso.herramientas_prohibidas):
            raise ErrorConfiguracion(f"Las herramientas prohibidas de {caso.id} no coinciden.")
