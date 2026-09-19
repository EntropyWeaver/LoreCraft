# Roles, personajes y comportamiento

Esta guía describe LoreCraft v0.2.0. La instalación editable del [README](../README.md) incluye los cuatro roles; no se instalan como plugins separados.

Un **rol del motor** es una tarea, como dirigir o archivar. Un **personaje** es una ficha de ficción, como Iria. El rol `actor` interpreta al personaje focal del turno; no necesitas crear un nuevo nodo para cada personaje.

## Qué recibe y devuelve cada rol

| Rol | Prompt | Datos que recibe | Resultado |
|---|---|---|---|
| Creador (`scenario`) | [scenario.txt](../ficcion/prompts/scenario.txt) | Semilla, estilo y fichas elegidas completas, incluidos sus secretos. | `ScenarioDraft`: escenario, reparto, situación inicial y asuntos abiertos. |
| Director (`director`) | [director.txt](../ficcion/prompts/director.txt) | Escena, recuerdos e historial públicos; nombres e IDs presentes; destinatario solicitado. Un mensaje privado aparece como un marcador, sin su contenido. | `TurnPlan`: personaje focal, ritmo, modo y límite de palabras. |
| Intérprete (`actor`) | [actor.txt](../ficcion/prompts/actor.txt) | Su propia ficha, recuerdos seleccionados permitidos, escena e historial visibles, mensaje actual, estilo y plan. | Texto narrativo para el jugador. |
| Archivista (`archivist`) | [archivist.txt](../ficcion/prompts/archivist.txt) | Escena visible para el focal, mensajes del turno con fuentes y audiencias, recuerdos de conocimientos del contexto de ese personaje. | `ArchiveProposal`: candidatos a eventos y recuerdos, y contradicciones. |

El creador se ejecuta cuando todavía no hay escenario. Los otros tres roles se ejecutan en cada turno. Los contratos están en [models.py](../ficcion/models.py); el ensamblado y la validación, en [engine.py](../ficcion/engine.py) y [llm.py](../ficcion/llm.py).

## Crear o cambiar un personaje

En el panel, abre **Crear una historia** y edita la ficha JSON antes de pulsar **Crear historia**. Ese formulario admite una ficha. Para un reparto de varios personajes, usa una semilla JSON desde la terminal y abre después la sesión en el panel con la misma carpeta de datos.

Copia [examples/kepler.json](../examples/kepler.json) o [examples/kepler_dos_personajes.json](../examples/kepler_dos_personajes.json). Una ficha contiene:

| Campo | Función | Ejemplo |
|---|---|---|
| `key` | Clave única y estable dentro de la semilla. Letras ASCII, números, `_` o `-`; hasta 64 caracteres. | `iria` |
| `name` | Nombre visible. | `Iria` |
| `identity` | Identidad, ocupación y contexto personal. | `Ingeniera de sistemas, 34 años` |
| `traits` | Rasgos concretos que orientan sus reacciones. | `["observadora", "independiente"]` |
| `voice` | Forma de expresarse: longitud, registro, humor, hábitos. | `Frases breves, humor seco ocasional` |
| `immediate_goal` | Objetivo propio en la escena. | `Restablecer el transmisor` |
| `relationship_to_player` | Relación inicial con el jugador. | `Se conocen de vista` |
| `known_facts` | Hechos que conoce desde el principio. | `["El apagón comenzó en comunicaciones"]` |
| `private_secrets` | Información privada del personaje. | `["Ocultó un informe de mantenimiento"]` |

Los campos de conocimientos y secretos admiten listas vacías. No añadas campos arbitrarios: los contratos rechazan claves desconocidas. Para incorporar un atributo nuevo, cambia primero el modelo Pydantic y revisa sus consumidores.

Describe comportamientos observables: «Responde con precisión y reserva las bromas para aliviar tensión» es más evaluable que «Tiene una personalidad increíble». Los ejemplos de voz extensos funcionan mejor como TXT seleccionables que dentro de una ficha obligatoria.

`known_facts` y `private_secrets` forman parte de la ficha que recibe su intérprete; no tienen interruptores individuales. Para un conocimiento que quieras activar o desactivar, impórtalo como recuerdo. El creador sí ve las fichas completas: revisa que no convierta un secreto en un hecho público del escenario.

## Cambiar escenario y estilo

La semilla contiene `title`, `brief`, `selected_character_cards`, `style_preferences` e `imported_fiction_memories`. Los valores de estilo son:

```json
{
  "language": "es",
  "tone": "tensión contenida, diálogo natural, detalles sensoriales breves",
  "default_max_words": 180
}
```

`default_max_words` admite de 40 a 1 000 palabras. El director elige una extensión igual o inferior; el motor avisa si la narración la supera, pero no corta el texto por palabras. El límite duro de generación se expresa en tokens y depende también de `output_caps`.

`imported_fiction_memories` de la semilla aporta datos al creador inicial. No crea los recuerdos seleccionables de la aplicación; para eso usa `import-txt` o el panel.

```powershell
$sesion = .\.venv\Scripts\python.exe -m ficcion new --seed examples/kepler_dos_personajes.json
.\.venv\Scripts\python.exe -m ficcion characters --session $sesion
```

`new` guarda la semilla y reserva IDs para sus personajes; no llama a un LLM. `characters` devuelve un objeto JSON cuyas claves son los IDs y cuyos valores son las fichas. Los IDs dependen de la sesión: no reutilices los de otra historia.

Editar el JSON original después de crear una sesión no modifica sus fichas guardadas. Para comprobar nuevos rasgos, crea una historia nueva. En v0.2.0 no hay edición de fichas persistidas ni entradas y salidas automáticas de personajes de la escena.

## Un turno completo con voz y conocimientos importados

Este ejemplo de PowerShell usa OpenAI. Prepara antes `.env` y el perfil como indica el README. Para un modelo local, sustituye la ruta del perfil por la tuya.

```powershell
$sesion = .\.venv\Scripts\python.exe -m ficcion new --seed examples/kepler_dos_personajes.json
$personajes = .\.venv\Scripts\python.exe -m ficcion characters --session $sesion | ConvertFrom-Json
$iriaId = ($personajes.PSObject.Properties | Where-Object { $_.Value.key -eq "iria" }).Name

$conocimientos = .\.venv\Scripts\python.exe -m ficcion import-txt --session $sesion --character-id $iriaId --file examples/iria_conocimientos.txt --kind knowledge | ConvertFrom-Json
$voz = .\.venv\Scripts\python.exe -m ficcion import-txt --session $sesion --character-id $iriaId --file examples/iria_estilo.txt --kind style | ConvertFrom-Json

$seleccion = @()
foreach ($id in (@($conocimientos.memory_ids) + @($voz.memory_ids))) {
    $seleccion += @("--memory", $id)
}

.\.venv\Scripts\python.exe -m ficcion turn --profile profiles/openai.json --session $sesion --focus $iriaId @seleccion --text "Hola, Iria. ¿Qué acceso queda abierto para llegar al transmisor?"
```

`--focus` exige que el personaje esté presente en la escena creada. El ejemplo de dos personajes pide que ambos estén en el taller. El motor valida esa presencia; si el modelo crea una escena distinta, inspecciona el resultado antes de continuar.

Los fragmentos de ambos archivos se seleccionan explícitamente. El siguiente turno sin `--memory` reutiliza la selección guardada; `--no-memories` la sustituye por una lista vacía. La selección se confirma con el turno exitoso.

Para dirigir una intervención privada:

```powershell
.\.venv\Scripts\python.exe -m ficcion turn --profile profiles/openai.json --session $sesion --focus $iriaId --visibility private --text "Quería preguntarte por el informe, sin que Dante lo oiga."
```

La intervención y su respuesta tendrán como audiencia solo a Iria. El director recibe un marcador de conversación privada, y el contexto posterior de Dante excluye ese intercambio. Para guardar una nota del jugador que no recibe ningún rol, usa el campo de nota privada del panel o `--private-thoughts`.

## Modificar los system prompts

Los cuatro archivos están en `ficcion/prompts/`. `RoleRunner.system_prompt()` los lee del paquete y `messages_for()` construye el mensaje de sistema separado del contexto variable. En una instalación editable, editar esos archivos cambia las llamadas nuevas; reinicia el panel si también has cambiado Python o dependencias.

Para ajustar una personalidad individual, usa su ficha. Para una regla de escritura común, edita `actor.txt`. Por ejemplo, puedes añadir:

> Prioriza una reacción concreta del personaje y un detalle del entorno. Evita resumir el diálogo anterior y no cierres todos los turnos con una pregunta.

Conserva las reglas de agencia y conocimientos del prompt base. El intérprete describe al personaje y lo que puede percibir; deja al jugador sus palabras, decisiones, sentimientos y aceptación. Un archivo de referencia se interpreta como datos de ficción, no como autoridad para cambiar esas reglas.

Al mensaje de sistema del intérprete se añade en Python una regla sobre `kind=style` y `kind=knowledge`. Los otros tres roles reciben además el esquema JSON de su contrato. Modificar el archivo TXT no elimina esas adiciones.

Para cambiar un rol que produce JSON:

1. Conserva los nombres de campo y valores permitidos, o modifica conjuntamente `models.py`, el prompt y su validación en `engine.py`.
2. Mantén las referencias a personajes, fuentes y audiencias. La aplicación valida esos IDs antes de guardar.
3. Ejecuta las pruebas y revisa una generación con el modelo real. `prompt` valida JSON en Python; `json_schema` exige además soporte del servidor.

El director solo admite `focus_character_id`, `pace` (`slow`, `normal`, `brisk`), `response_mode` (`dialogue`, `action`, `mixed`) y `max_words`. Pedirle un plan libre requiere ampliar el contrato; no basta con añadirlo al prompt.

El archivista distingue hechos establecidos, intentos, afirmaciones y creencias. Propone recuerdos pendientes de aprobación; no escribe libremente en SQLite. Si declara contradicciones, se guarda el diálogo sin aplicar las propuestas de eventos o recuerdos de ese turno.

Una petición ya completada con el mismo `turn_id` devuelve el resultado archivado. Para probar un prompt nuevo, envía un turno con ID nuevo; para comparar estilos sin arrastrar el historial anterior, usa una historia nueva. Conserva el prompt usado en el inspector o en el informe de evaluación.

Los cuatro prompts incluidos parten del texto de [ESPECIFICACION.md](ESPECIFICACION.md). Si los cambias, registra esa modificación en Git y actualiza el diseño cuando cambie el contrato o la responsabilidad del rol.

## Añadir un quinto rol o usar modelos distintos

Estas son ampliaciones de código, no opciones ya implementadas. Añadir otro TXT por sí solo no hace que LangGraph lo ejecute.

Para una tarea nueva, define sus datos de entrada y resultado; añade el contrato Pydantic si genera JSON, su prompt y un método de nodo en `FictionEngine`. Registra el nodo y sus conexiones en `_build_graph()`. Si añade datos al estado, amplía `NarrativeState`. Revisa también presupuesto, caché, auditoría y las pruebas del primer turno y de reintentos.

Mantén el filtrado en `context.py` y las validaciones del motor. Un revisor de la voz de Iria necesita la información permitida a Iria, no las fichas privadas de todo el reparto. Un nodo adicional tampoco debe confirmar fragmentos de una historia antes de `save_turn`.

El punto de extensión para otros proveedores es `Backend.complete(role, messages, schema, max_tokens)`. Asignar modelos distintos a roles requiere además elegir el contador y las reservas correctas para cada llamada; cambiar únicamente el transporte dejaría el presupuesto calculado para otro modelo. No hay un registro de plugins ni enrutamiento por rol listo para configurar en esta versión.

## Verificar un cambio de comportamiento

Primero ejecuta `python -m pytest -q` con el Python de tu entorno virtual. Las respuestas de las pruebas son simuladas: verifican infraestructura, filtrado y persistencia.

Después usa `ficcion eval --profile TU_PERFIL --max-turns 1` y, cuando funcione, `--max-turns 6`. Comprueba que la voz aparezca en el diálogo sin recitar la ficha, que se conserven los hechos, que el personaje no decida por el jugador y que no revele conocimientos ajenos. Las puntuaciones humanas del informe empiezan vacías; acompaña cada valoración con un pasaje concreto.
