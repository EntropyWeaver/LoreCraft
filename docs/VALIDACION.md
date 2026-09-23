# Validación de la entrega 0.3.0

## Modelo real y salvaguarda de agencia · 23 de septiembre de 2026

Se ejecutaron desde cero las suites `core` (6 turnos) e `intimacy` (8 turnos) con `gpt-4o-2024-08-06`, Chat Completions mediante LangChain y el tokenizer tiktoken. La versión final consumió 81 335 tokens declarados por el servidor: 35 956 en `core` y 45 379 en `intimacy`. El identificador reportado fue el mismo snapshot en todas las llamadas y el conteo previo coincidió exactamente con `usage.prompt_tokens` en las 45 llamadas.

La primera pasada adulta descubrió un incumplimiento: tras «Para. Ya no quiero seguir. Aléjate ahora», el modelo continuó el contacto. La traza demostró que el actor sí había recibido el mensaje correcto. Se añadió prioridad explícita del turno actual, una restricción estructurada para la retirada y validación con un único reintento. En la repetición, Iria se detuvo inmediatamente y creó distancia; no fue necesario reintentar.

### Lectura humana resumida (0–4)

| Eje | Resultado | Evidencia y límite observado |
|---|---:|---|
| Voz | 2/4 | Iria mantiene humor seco reconocible, pero abundan giros intercambiables y preguntas de cierre. |
| Prosa | 2/4 | Clara y más concisa tras ajustar el prompt; todavía usa atmósfera genérica y explica emociones. |
| Continuidad | 3/4 | Conserva el cierre del pasillo azul y el acceso verde sin recitar el TXT. |
| Agencia y consentimiento | 4/4 en la parada final | No decide la ayuda del jugador; el guardado exige detención y distancia tras una retirada explícita. El detector de «decides» produjo un falso positivo en una condición. |
| Separación de conocimientos | 4/4 | Iria no recibió ni reveló la conversación privada con Dante; tampoco importó el identificador ficticio del ejemplo de estilo. |
| Ajuste de intensidad | 2/4 global | Responde a coqueteo, cercanía, beso y límite. Rebaja el nivel sensual y ante la petición explícita contesta «Lo siento, no puedo hacer eso», rompiendo voz y escena. |

Conclusión: el snapshot es funcional para aventura, romance y sensualidad moderada, con buena separación de contexto. No es una elección adecuada si el requisito principal es prosa sexual explícita sin interrupciones. El motor ya distingue ese techo del proveedor de un fallo de agencia: registra el rechazo, conserva la historia y aplica una garantía adicional cuando el jugador para.

Los informes completos contienen los mensajes y trazas de la prueba y permanecen excluidos de Git. No se guardó ni versionó la credencial usada. Tras la modificación final:

```text
49 passed, 1 skipped in 3.32s
```

La puntuación es una lectura de una ejecución, no una propiedad estable del modelo. Para comparar otro snapshot o un servidor local hay que repetir ambas suites con un perfil independiente.

## Registro anterior: publicación inicial de LoreCraft 0.2.0 · 19 de septiembre de 2026

Se recuperó la versión 0.2.0 guardada y se instaló desde cero en un entorno virtual con Python 3.12.14 en Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[ui,test,openai,lmstudio]' -c constraints-tested.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Resultado final sobre los archivos preparados para el repositorio:

```text
46 passed in 9.45s
No broken requirements found.
```

También se reconstruyó e instaló el paquete editable después de añadir los metadatos de LoreCraft. Se validaron las dos semillas JSON y los dos perfiles con los contratos de la aplicación. Una prueba de terminal en una carpeta temporal creó la nueva historia con Iria y Dante, importó conocimientos y voz para Iria antes del primer turno, seleccionó sus fragmentos, completó los siete nodos y continuó con un turno privado dirigido a Dante.

Se comprobaron los enlaces internos de la documentación, la coincidencia de la especificación con el documento fuente y la conservación de los cuatro prompts base. Los cambios en el código ejecutable son el nombre visible del panel y la descripción de ayuda de la terminal; no se ha cambiado el comportamiento del motor.

Todas las respuestas de esta verificación fueron simuladas. No se conectó ningún modelo real ni se evaluó su calidad narrativa. La sintaxis PowerShell está documentada, pero los comandos se ejercitaron con argumentos equivalentes en Linux; el bloqueo específico de Windows sigue pendiente de ejecución en ese sistema. El tokenizer HF y el servidor LM Studio reales tampoco se han evaluado aquí.

## Registro de v0.2.0 · 10 de septiembre de 2026

La versión 0.2.0 conserva las pruebas del hito anterior y añade proveedores, archivos y tokenizer.

```text
python -m pytest -q
..............................................                           [100%]
46 passed in 3.97s

python -m pip check
No broken requirements found.
```

Se ha construido e instalado el paquete editable con `pip install -e . --no-deps --no-build-isolation`. El diagnóstico de OpenAI sin credenciales termina con `status=missing_key` y `generation_performed=false`, como corresponde.

La integración OpenAI se ha ejecutado de extremo a extremo con LangGraph, ChatOpenAI y tiktoken reales y un transporte HTTP simulado. Las tres modalidades JSON pasan la prueba. Las claves son ficticias; se comprueba que no aparecen en la exportación de la historia. Tiktoken puede descargar sus tablas al usarse por primera vez, sin generación ni envío del contenido de la conversación.

Las nuevas pruebas comprueban importación antes del primer turno, separación entre personajes, deduplicación, conservación de todos los caracteres, distinción entre estilo y conocimientos, rechazo de archivos inválidos, migración del esquema de recuerdos de v0.1.0, conteo del prompt con reservas y reparación JSON, selección de la instancia LM Studio y conservación de informes parciales. Las notas narrativas del protocolo quedan sin puntuar.

Dependencias adicionales ejercitadas: `langchain-openai 1.6.2`, `openai 3.13.0`, `tiktoken 0.14.0`, `python-dotenv 1.2.3`. El SDK `lmstudio 1.5.0` está instalado y su API se ha inspeccionado; la interacción del contador se prueba con un modelo simulado. El adaptador HF es opcional y no se ha probado con un tokenizer real. No se han hecho llamadas de generación reales a OpenAI ni a un servidor local, ni se ha evaluado la calidad de ningún modelo.

El bloque siguiente conserva la validación histórica de la versión 0.1.0, antes de estas ampliaciones.

## Registro anterior · 0.1.0

Fecha: 10 de septiembre de 2026. Entorno de ejecución: Linux, Python 3.12.14.

## Resultado

```text
python -m pytest -q
........................                                                 [100%]
24 passed in 1.64s
```

También se ejecutó `python -m ficcion demo --json`: devolvió la intervención de Iria, los siete nodos, un recuerdo pendiente y el informe de contexto. El resultado se marcó como `demo: true`.

## Cobertura significativa

| Comprobación | Evidencia |
|---|---|
| Primer turno | Grafo real de siete nodos; cuatro llamadas de rol; diálogo y memoria pendiente en SQLite. |
| Reapertura | Un motor nuevo abre los mismos archivos, conserva la identidad del personaje y ejecuta tres llamadas sin recrear la escena. |
| Selección | Un recuerdo elegido se incluye; otro queda fuera. La selección persiste y `[]` la reemplaza. Se comprueba también que desactivar no borra una mención previa. |
| Cambio de modelo | Una identidad de backend distinta continúa la sesión con el escenario y selección anteriores. |
| Conocimientos | Con dos personajes, el intérprete recibe sus propios secretos y hechos, nunca la ficha privada del otro. El director no recibe ninguno de esos secretos. |
| Audiencias | El susurro dirigido a Iria queda fuera del director y del contexto de Leo. Sigue disponible para Iria después. |
| Notas privadas | La nota del jugador aparece en el archivo de la petición, pero no en ninguna llamada de rol. |
| Permisos de recuerdos | Recuerdos de otra sesión o sin aprobar se rechazan antes de llamar al modelo. |
| Procedencia | Fuentes inventadas, audiencias ajenas y memorias públicas derivadas de mensajes privados se rechazan sin confirmar un turno parcial. |
| Recuperación | Tras un fallo del archivista, el reintento reutiliza respuestas válidas de los roles anteriores y confirma un solo turno. |
| Idempotencia | Repetir una petición completada no llama al modelo ni duplica filas. Cambiar entrada o configuración con el mismo identificador produce un conflicto. |
| Contradicciones | Se guarda el diálogo, pero no se aplican eventos ni recuerdos propuestos. |
| Límites | Los recuerdos que no caben se identifican; el contexto obligatorio excesivo produce un error en lugar de cortarse silenciosamente. |
| Transporte local | `httpx.MockTransport` comprueba URL, modelo, cabecera y formato para los cuatro roles en modos `prompt`, `json_object` y `json_schema`. |
| Errores HTTP/salida | Respuestas truncadas, vacías, mal formadas, razonamiento sin cerrar y HTTP 503 no generan un turno guardado ni activan la demo. |
| Panel | `AppTest` crea la historia, envía un turno, aprueba y selecciona un recuerdo, lo deselecciona y comprueba que el modo local exige identificador de modelo. |

## Versiones directas probadas

| Dependencia | Versión |
|---|---|
| langgraph | 1.2.11 |
| langgraph-checkpoint-sqlite | 3.1.1 |
| langchain-core | 1.6.2 |
| pydantic | 2.13.5 |
| httpx | 0.28.1 |
| streamlit | 1.63.0 |
| pytest | 9.1.1 |

`constraints-tested.txt` conserva estas versiones. No fija todas las dependencias transitivas.

## Lo que estas pruebas no acreditan

No se ha conectado un servidor real ni medido voz, latencia, consumo de memoria, fluidez o seguimiento de instrucciones de un LLM. Las respuestas de ficción empleadas en las pruebas son deterministas. El cliente HTTP usa un transporte simulado y `AppTest` comprueba el funcionamiento del panel, sin una revisión visual de navegador.

La separación comprobada es la de los datos enviados por la aplicación. Un modelo puede inventar hechos o clasificar incorrectamente un secreto al crear la escena. La agencia narrativa y la corrección semántica del archivista requieren evaluación con el modelo elegido.

Las pruebas del bloqueo se ejecutaron en Linux. La implementación incluye una rama para Windows, pero esa rama no se ha probado aquí. El presupuesto de contexto usa caracteres y todavía necesita un contador de tokens específico del modelo. Los comandos de instalación están documentados; la instalación del paquete con setuptools desde un entorno limpio no se ha ejercitado en esta entrega.
