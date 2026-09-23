# Modelos, tokenizer y memoria seleccionable

LoreCraft v0.3.1 separa el estado de la historia del proveedor. Puedes cambiar de modelo entre turnos y conservar la sesión, aunque el cambio puede afectar a la voz y a la continuidad. Para comparar modelos, crea sesiones de evaluación independientes.

## Elegir la ruta de ejecución

| Ruta | Configuración | Qué ejecuta |
|---|---|---|
| Demo | `ficcion demo` o **Demo de funcionamiento** | Respuestas fijas de prueba; LangGraph y SQLite reales. |
| OpenAI | `profiles/openai.json` y `OPENAI_API_KEY` | Chat Completions mediante `ChatOpenAI.invoke()`. |
| OpenAI legacy | `profiles/openai-gpt35.json` y `OPENAI_API_KEY` | Benchmark de GPT-3.5 Turbo; no recomendado para los roles estructurados. |
| LM Studio | Copia de `profiles/lmstudio.json` con un ID cargado | Chat Completions por HTTP y conteo nativo mediante el SDK. |
| Otro servidor compatible | Perfil `provider=local`, con contador HF local o `characters` | El mismo transporte HTTP; el servidor debe admitir los mensajes y parámetros enviados. |

El perfil OpenAI conserva `gpt-4o-2024-08-06` como ejemplo. La [ficha oficial](https://developers.openai.com/api/docs/models/gpt-4o), consultada el 19 de septiembre de 2026, lista esa snapshot y Chat Completions. El acceso depende de la cuenta y puede cambiar. LoreCraft no incluye una clave, una suscripción ni pesos.

## Perfiles JSON

Copia un perfil a `profiles/private-mi-modelo.json`, edítalo y pásalo a `--profile`. El prefijo `private` permite mantener esa configuración fuera de Git. Los valores del perfil prevalecen sobre los flags antiguos `--model`, `--base-url`, `--json-mode` y `--backend` del comando `turn`.

El panel **no importa perfiles JSON**. Construye su configuración con los controles de la barra lateral; para ajustar los demás parámetros, usa la terminal o modifica la creación de `ModelProfile` en `app.py`.

| Campo | Comportamiento |
|---|---|
| `provider` | `local` u `openai`. |
| `model` | Identificador exacto servido o disponible para la cuenta. Se exige para generar. |
| `base_url` | URL base sin `/chat/completions`; por ejemplo, `http://127.0.0.1:1234/v1`. OpenAI exige `https://api.openai.com/v1`. |
| `tokenizer` | `lmstudio`, `hf`, `openai` o `characters`. OpenAI exige su contador. |
| `tokenizer_path` | Carpeta local del tokenizer HF. Si es relativa, se resuelve respecto al archivo del perfil. |
| `context_window` | Límite de trabajo en tokens. Obligatorio para HF y OpenAI. Con LM Studio, `null` usa la ventana cargada; un número puede reducirla. |
| `safety_tokens` | Margen adicional reservado. El ejemplo OpenAI usa 256; el local, 128. |
| `temperature` | Temperatura del intérprete, entre 0 y 2; predeterminada 0.7. Creador, director y archivista usan 0.2 en ambos adaptadores. |
| `output_caps` | Topes positivos por rol: `scenario`, `director`, `actor`, `archivist`. Se combinan con la petición del motor, como explica la tabla siguiente. |
| `json_mode` | `prompt`, `json_object` o `json_schema`. Solo afecta a los tres roles con contrato JSON. |
| `timeout` | Tiempo de espera HTTP en segundos; 120 por defecto y hasta 600. |
| `extra_body` | Parámetros de muestreo adicionales compatibles con el servidor. Se admiten `seed`, `top_p`, `top_k`, `repeat_penalty`, `frequency_penalty` y `presence_penalty`. |

`extra_body` se envía a todos los roles. Que LoreCraft admita una clave no implica que OpenAI o tu servidor la acepten: por ejemplo, un servidor puede rechazar `top_k`. El perfil rechaza claves desconocidas y no permite sustituir modelo, mensajes o formato a través de ese objeto.

Para probar una voz más variable, cambia `temperature` manteniendo el resto del perfil y de la semilla. Para cambiar la personalidad o el ritmo narrativo, modifica primero la ficha o los prompts: el muestreo no define esos comportamientos.

## Credenciales y diagnóstico

El cargador de `.env` lee solamente:

```dotenv
OPENAI_API_KEY=
FICTION_API_KEY=
```

Una variable de entorno no vacía tiene prioridad sobre el archivo. El archivo no interpola otras variables. No añadas credenciales a fichas, TXT o perfiles: las credenciales se usan en el transporte, no como memoria del personaje.

```powershell
.\.venv\Scripts\python.exe -m ficcion doctor --profile profiles/openai.json --env-file .env
```

`doctor` consulta `/models` y prueba el contador sin generar ficción. No establece por sí solo que haya saldo ni que la generación acepte todos los parámetros. El diagnóstico listo indica que se puede pasar al primer turno real.

| Estado | Siguiente paso |
|---|---|
| `missing_key` | Configura la clave del proveedor. |
| `needs_model` | Elige uno de los IDs anunciados. |
| `model_not_listed` | Comprueba el ID, su disponibilidad y las credenciales. |
| `ready_for_generation_test` | Ejecuta un turno o `eval --max-turns 1`. |
| `ready_without_tokenizer` | Hay conexión, pero usas presupuesto por caracteres. |
| `context_too_small` | Revisa la ventana y las reservas. |
| `http_error` / `error` | Revisa URL, estado HTTP, autenticación, SDK y mensaje de error. |

## Presupuesto de contexto

Con tokenizer, cada llamada debe cumplir:

```text
tokens del prompt completo + reserva de salida + margen <= ventana de contexto
```

Se cuenta el sistema, el esquema JSON, los datos y los mensajes de reparación si los hay. Se eliminan primero turnos antiguos completos y después recuerdos desde el final de la selección, que tienen menor prioridad. El sistema, la ficha, la escena obligatoria y la entrada actual no se recortan silenciosamente. Si no caben, el turno falla antes de enviarse.

Los topes del perfil son un techo: la reserva efectiva es el menor valor entre `output_caps[rol]` y la petición del motor.

| Rol | Petición del motor | Tope en los perfiles incluidos |
|---|---|---|
| Creador | 4 096 tokens | 2 048 |
| Director | 512 tokens | 512 |
| Intérprete | `max(512, max_words * 4)` | 1 024 |
| Archivista | 2 048 tokens | 1 536 |

Por ejemplo, con un plan de 180 palabras, el intérprete pide 720 tokens; un tope de 1 024 no eleva esa reserva a 1 024. Para respuestas más largas, ajusta también `style_preferences.default_max_words` al crear la historia. Elevar un tope por encima de la petición del motor no aumenta la salida; superar esas peticiones requiere modificar `engine.py`.

En `tokenizer=characters` no hay `TokenBudget`: `context_window`, `safety_tokens` y `output_caps` no controlan el presupuesto. Se usa el límite de caracteres y las peticiones de salida del motor. Ese modo ayuda a comprobar el transporte, pero no verifica que el contexto quepa en tokens.

| Contador | Alcance y límites |
|---|---|
| LM Studio | Aplica la plantilla y tokenizer de la instancia ya cargada y consulta su ventana real. El contador requiere una URL HTTP directa terminada en `/v1`. No carga ni descarga modelos. |
| OpenAI | LangChain cuenta con tiktoken y estima el overhead del chat. El motor compara el resultado con `usage.prompt_tokens`; no promete igualdad exacta. La primera ejecución puede descargar la tabla de codificación. |
| HF local | Usa `apply_chat_template`, `local_files_only=True` y `trust_remote_code=False`. Requiere los archivos y una plantilla compatible con el modelo servido; no descarga un tokenizer automáticamente. |

El SDK LM Studio 1.5.0 fijado en `constraints-tested.txt` no acepta `api_token` en su constructor. Si el servidor exige autenticación, el contador produce un error: usa un tokenizer HF que coincida con el servidor, o valida un SDK compatible antes de cambiar la restricción. No basta con añadir `FICTION_API_KEY` para que ese SDK admita autenticación.

Sigue existiendo un límite independiente de 60 000 caracteres por prompt completo. Se cambia con `FictionEngine(..., max_prompt_chars=...)`, no en el perfil. El contexto considera como máximo los últimos 20 turnos y 12 eventos visibles; todo el historial permanece archivado.

## TXT de conocimientos y de voz

| Tipo y ámbito | Uso |
|---|---|
| `knowledge` + `character` | Datos que puede recibir el personaje dueño. |
| `knowledge` + `scenario` | Datos compartidos del escenario, disponibles en los contextos públicos y de personajes. |
| `style` + `character` | Ejemplos de cómo habla o escribe ese personaje; no deberían establecer hechos nuevos. |

El importador admite `.txt` UTF-8, con o sin BOM, no vacío y de hasta 512 KiB. Guarda su contenido completo y SHA-256 en SQLite y crea fragmentos de hasta 1 600 caracteres, más la etiqueta de procedencia. Reimportar los mismos bytes al mismo ámbito, dueño y tipo devuelve los IDs anteriores.

Importar aprueba los fragmentos, pero la recuperación sigue siendo seleccionable. En la terminal pásalos mediante `--memory`; en el panel usa la casilla de activación y el selector. La [guía de personajes](ROLES_Y_PERSONAJES.md#un-turno-completo-con-voz-y-conocimientos-importados) muestra cómo importar y seleccionar todos los fragmentos antes del primer turno.

El selector no es una búsqueda vectorial: el motor prueba los recuerdos elegidos en su orden y muestra los que omite por falta de espacio. El archivo entero se conserva, aunque no todos sus fragmentos entren en una llamada.

Un TXT de respuestas anteriores se usa como referencia de voz, sin reproducirlo como una conversación histórica auténtica. No supone entrenamiento ni fine-tuning. No modifica los pesos del modelo.

Desactivar un recuerdo evita recuperarlo otra vez, pero no borra sus menciones en el historial ni los eventos ya guardados. Si necesitas evaluar al personaje sin ese contexto previo, crea una historia nueva.

## Evaluar y conservar resultados

```powershell
.\.venv\Scripts\python.exe -m ficcion eval --profile profiles/openai.json --max-turns 1
.\.venv\Scripts\python.exe -m ficcion eval --profile profiles/openai.json --suite core --max-turns 0
.\.venv\Scripts\python.exe -m ficcion eval --profile profiles/openai.json --suite intimacy --max-turns 0
```

El protocolo crea una historia independiente por ejecución y guarda `report.json`, `report.md` y SQLite en `reports/ID/`. Registra perfil, respuestas, prompts, tokens, omisiones y tiempos. Guarda un informe parcial si falla.

Un primer turno realiza normalmente cuatro llamadas al LLM; la suite `core`, 19; y `intimacy`, 25. Cada rol JSON permite un reintento. La retirada explícita del consentimiento valida también la salida narrativa y permite una corrección antes de rechazar el turno. Estas evaluaciones sí usan tu proveedor; las pruebas de pytest usan HTTP simulado.

Las seis dimensiones empiezan en `null`. Complétalas de 0 a 4 siguiendo la rúbrica y añade ejemplos. Las señales automáticas de filtración, rechazo o frases que podrían decidir por el jugador son ayudas para revisar, con posibles falsos positivos y negativos.

## Problemas frecuentes

| Problema | Qué comprobar |
|---|---|
| `No module named ...` | Instala los extras con el mismo Python de `.venv` que ejecuta la aplicación. |
| La clave de `.env` no se usa | Ejecuta desde la raíz o pasa `--env-file`. Usa `--profile`; el recorrido local antiguo lee la clave del entorno del proceso. |
| Edito el perfil y el panel no cambia | El panel usa sus controles. Los perfiles se aplican en la terminal. |
| Edito `examples/kepler.json` y no cambia la historia | Crea una sesión con `new --seed examples/kepler.json`. Las fichas existentes están guardadas en SQLite; el ejemplo predeterminado del panel procede de `ficcion/kepler.json`. |
| El modelo devuelve JSON inválido | Empieza por `json_mode=prompt`, conserva los contratos y revisa el prompt y la capacidad del modelo. Los modos estructurados requieren soporte del servidor. |
| Salida truncada | Revisa la reserva efectiva del rol en el inspector, los topes del perfil y las peticiones de `engine.py`. |
| No cabe el prompt obligatorio | Reduce ficha/entrada o aumenta una ventana realmente soportada. Revisa también el límite de 60 000 caracteres. |
| Faltan recuerdos seleccionados | Revisa las omisiones y su prioridad. La selección no garantiza que todos quepan. |
| El contador difiere de `usage` | Comprueba tokenizer y plantilla; en OpenAI existe overhead estimado. |
| Un turno fallido da conflicto al cambiar el modelo | Un `turn_id` identifica una entrada y configuración concretas. Al cambiarla, usa un ID nuevo. |
| El mismo turno devuelve la respuesta anterior | Es la recuperación idempotente de una petición completada. Prueba el cambio con un turno nuevo. |
| La narración sigue usando información desactivada | Puede haberse incorporado al historial o a eventos. Prueba una historia nueva. |

Para copiar una historia, cierra la aplicación y respalda la carpeta de datos completa. `ficcion export --session ID --output exports/historia.json` facilita la inspección; la importación de esa exportación todavía no está implementada. El inspector y los informes son vistas completas de autor y pueden contener secretos del reparto y notas del jugador. El panel es local y no incluye autenticación para varios clientes.
