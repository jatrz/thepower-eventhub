---
license: apache-2.0
base_model: Qwen/Qwen2.5-1.5B-Instruct
library_name: peft
tags:
- lora
- text-classification
- spanish
- customer-support
---

# Clasificador de mensajes de clientes en español

Adaptador LoRA de **Qwen/Qwen2.5-1.5B-Instruct** para clasificar mensajes de atención al cliente en cuatro categorías:

- `pedido`
- `devolucion`
- `queja`
- `otro`

## Uso previsto
Proyecto educativo y demostración de ajuste fino eficiente con LoRA. No está validado para decisiones empresariales sin evaluación adicional.

## Entrenamiento
- Dataset sintético: 300 ejemplos, 75 por categoría.
- Entrenamiento: 250 ejemplos.
- Prueba reservada: 50 ejemplos.
- Técnica: LoRA (PEFT).
- Modelo base: [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct).

## Resultados en el conjunto de prueba
- Modelo base: 34/50 (68.0%).
- Modelo con LoRA: 42/50 (84.0%).

Los resultados corresponden únicamente al conjunto sintético utilizado en esta práctica y no garantizan el rendimiento con mensajes reales.

## Cargar el adaptador
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
import torch

base_id = "Qwen/Qwen2.5-1.5B-Instruct"
adapter_id = "javiz12188/qwen2.5-1.5b-clasificador-clientes-lora"
tokenizer = AutoTokenizer.from_pretrained(base_id)
base = AutoModelForCausalLM.from_pretrained(
    base_id, torch_dtype=torch.float16, device_map="auto"
)
model = PeftModel.from_pretrained(base, adapter_id)
```
