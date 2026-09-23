# Cambios

## motor_ficcion 0.3.1 · 2026-09-23

- Perfil reproducible `profiles/openai-gpt35.json` para comparar el alias legacy `gpt-3.5-turbo`.
- La retirada del consentimiento exige ahora dos evidencias distintas: cese de contacto y creación de distancia.
- Evaluación real de GPT-3.5 Turbo documentada: el alias resolvió a `gpt-3.5-turbo-0125`, falló en roles estructurados y no aumentó la explicitud del actor.

## motor_ficcion 0.3.0 · 2026-09-23

- Evaluación real reproducible con suites `core` e `intimacy`, rúbrica humana 0–4, señales de rechazo y uso agregado del servidor.
- El intérprete prioriza el mensaje actual, evita relleno genérico y trata los límites del jugador como restricciones del turno.
- Una retirada explícita del consentimiento exige una detención y distancia visibles; la salida se corrige una vez o el turno falla sin guardarse.
- Perfil OpenAI ajustado a 128 000 tokens para `gpt-4o-2024-08-06`, con conteo tiktoken contrastado contra el servidor.
- 49 pruebas superadas y una omitida por depender de un servicio externo.

## LoreCraft · publicación inicial del repositorio · 2026-09-19

- Importación de `motor_ficcion` v0.2.0 en `EntropyWeaver/LoreCraft`.
- README para clonar, instalar, ejecutar, configurar y modificar el proyecto.
- Guías de roles y personajes, modelos, tokenizer, memorias y evaluación.
- Ejemplo de Kepler con Iria y Dante, voces y conocimientos separados.
- Nombre LoreCraft en el panel y en la ayuda de terminal; el paquete sigue siendo `motor-ficcion` v0.2.0.
- Exclusiones de Git para claves, datos de sesiones, informes, exportaciones y pesos locales.

## motor_ficcion 0.2.0 · 2026-09-10

- OpenAI mediante LangChain, perfiles de proveedor y claves desde `.env`.
- Importación TXT por personaje para conocimientos o referencias de voz.
- Presupuesto con tokenizer LM Studio, OpenAI o adaptador HF local opcional.
- Diagnóstico sin generación y protocolo de evaluación de seis turnos.
- Ampliación a 46 pruebas, con inferencia simulada.

## motor_ficcion 0.1.0 · 2026-09-10

- Grafo LangGraph de siete nodos y cuatro system prompts.
- SQLite, selección explícita de recuerdos, validación de fuentes y audiencias.
- Primer escenario con Iria, panel Streamlit, terminal y adaptador local.
- 24 pruebas del grafo, persistencia, transporte y panel.
