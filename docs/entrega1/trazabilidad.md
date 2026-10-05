# Matriz de trazabilidad: Entrega 1

ST0255 Telemática, 2026-2. Emmanuel Hernández. 4 de octubre de 2026.

Esta matriz relaciona cada requisito del enunciado con la sección donde se responde y con la evidencia que lo demostrará cuando exista implementación. Abreviaturas:

- `P §n`: sección n de `docs/entrega1/propuesta.md`.
- `E §n`: sección n de `docs/protocolo/MCD-1.0.md`.
- `D:archivo`: diagrama en `docs/diagramas/`.

Columna "Origen":

- Exigido: el enunciado lo pide de forma obligatoria.
- Recomendado: el enunciado lo sugiere ("se recomienda", "puede").
- Decisión: no lo pide el enunciado; lo agregué porque otro requisito lo necesita.

Columna "Estado":

- Diseñado: la Fase 1 lo resuelve por completo con documentación.
- Diseñado, F2 / Diseñado, F3: la decisión está tomada y documentada; la evidencia llega con la implementación de esa fase.
- Por confirmar: depende de una respuesta del profesor.

## 1. Fase 1: propuesta inicial

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia | Estado |
|---|---|---|---|---|---|
| F1.1 | "descripción general del problema" | Exigido | P §2 | Este documento | Diseñado |
| F1.2 | "arquitectura propuesta" | Exigido | P §4; D:despliegue.mmd | Este documento | Diseñado |
| F1.3 | "entidades participantes" | Exigido | P §5; E §2.2 | Este documento | Diseñado |
| F1.4 | "tipos de mensajes" | Exigido | P §6; E §5 | Este documento | Diseñado |
| F1.5 | "sintaxis preliminar" | Exigido | P §7; E §4 | `tools/validar_ejemplos.py`: validación automatizada del formato, claves únicas y límite de 512 bytes | Diseñado |
| F1.6 | "reglas básicas de comunicación" | Exigido | P §8 y §11; E §6 y §7 | Este documento | Diseñado |
| F1.7 | "máquinas de estado" | Exigido | P §9; E §9; D:fsm-nodo, fsm-servidor-nodo, fsm-sesion-admin, fsm-cliente | Este documento | Diseñado |
| F1.8 | "análisis preliminar sobre el uso de TCP y UDP" | Exigido | P §10 | Matriz de 9 criterios | Diseñado |
| F1.9 | "exposición corta en clase ... aproximadamente cinco minutos" | Exigido si el grupo es seleccionado | `docs/entrega1/exposicion.md` | Ensayo cronometrado | Diseñado |

## 2. Requerimientos generales

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| R1 | "al menos 2 nodos que reportan métricas, un servidor central y uno o varios clientes de administración" | Exigido | P §4, §5 | Demostración con `nodo-01`, `nodo-02` y un cliente | Diseñado, F2 |
| R2 | "No hay comunicación directa entre nodos y clientes" | Exigido | P §4.2; E §2.2 | Solo el servidor escucha; captura Wireshark sin tráfico nodo-cliente | Diseñado, F2 |
| R3a | "registrar los nodos que participan en el sistema" | Exigido | E §5.2, §7.2; D:secuencia-registro | Log de `REGISTER` y `REGISTER_OK` | Diseñado, F2 |
| R3b | "recibir información periódica sobre su estado" | Exigido | E §5.4, §7.3; D:secuencia-telemetria | Captura UDP y log | Diseñado, F2 |
| R3c | "recibir eventos generados por los nodos" | Exigido | E §5.5, §7.4; D:secuencia-evento | Log de `EVENT` y `ACK` | Diseñado, F2 |
| R3d | "mantener información sobre el estado de los nodos conectados" | Exigido | E §7.3, §7.8, §9.2; D:fsm-servidor-nodo | Respuesta a `LIST` y `STATUS` con cambios de estado | Diseñado, F2 y F3 |
| R3e | "responder consultas realizadas sobre la infraestructura" | Exigido | E §5.8, §5.9, §7.6; D:secuencia-consulta | Cliente mostrando respuestas | Diseñado, F2 |
| R3f | "atender múltiples clientes de manera concurrente" | Exigido | P §14; E §10 | Prueba con varios clientes y nodos simultáneos | Diseñado, F3 |
| R4a | "El código no puede tener direcciones IP codificadas. Debe resolver nombres de dominio" | Exigido | P §13; E §12 | Búsqueda de patrones de IP en el código con resultado vacío; configuración con FQDN | Diseñado, F2 |
| R4b | "Si la resolución falla, el servicio debe manejar la excepción sin finalizar su ejecución" | Exigido | P §13; E §7.9, §12; D:secuencia-servicios-caidos | Prueba apagando BIND9 | Diseñado, F3 |
| R5 | "interfaz de visualización sencilla ... estados instantáneos de los nodos y, al menos, 5 datos históricos" | Recomendado | P §5; E §5.8 (`HISTORY` hasta 10); E §9.4 | Captura de la ventana Tkinter | Diseñado, F2 |
| R6a | "mecanismo de autenticación y gestión de perfiles de usuario" | Exigido | P §12; E §7.5 | Login con `admin` y con `operador`; 403 al operador en `EVENTS` | Diseñado, F2 y F3 |
| R6b | "evitar implementar un sistema de usuarios basado únicamente en archivos locales o bases de datos propias" | Recomendado | P §12 (OpenLDAP) | LDIF de ejemplo sin claves en `infra/ldap/` | Diseñado; uso de `libldap` por confirmar |
| R7a | "registro de un nodo" | Exigido | `REGISTER` (E §5.2) | Log | Diseñado |
| R7b | "envío de información periódica de estado" | Exigido | `TELEMETRY` (E §5.4) | Captura | Diseñado |
| R7c | "envío de un evento" | Exigido | `EVENT` (E §5.5) | Log | Diseñado |
| R7d | "confirmación o respuesta cuando sea necesaria" | Exigido | `REGISTER_OK`, `ACK`, `LOGIN_OK`, `BYE` (E §5) | Log | Diseñado |
| R7e | "consulta de información" | Exigido | `LIST`, `STATUS`, `HISTORY`, `EVENTS` (E §5.8) | Log | Diseñado |
| R7f | "respuesta a una consulta" | Exigido | `RESPONSE` e `ITEM` (E §5.9) | Log | Diseñado |
| R7g | "reporte de errores" | Exigido | `ERROR` y tabla de códigos (E §5.10, §6) | Pruebas con mensajes inválidos | Diseñado |
| R8 | "describir la especificación del servicio, el vocabulario de mensajes, las reglas de procedimiento ... suficientemente clara para permitir que una persona diferente pueda implementar el protocolo" | Exigido | E completo | Revisión cruzada independiente y `tools/validar_ejemplos.py`; los ejemplos válidos cumplen el formato y el límite de tamaño | Diseñado |
| R8a | "Visión General del Protocolo" | Recomendado (estructura tipo RFC 793) | E §2 | | Diseñado |
| R8b | "Especificación del Servicio ... primitivas" | Recomendado | E §3 | | Diseñado |
| R8c | "Formato de Mensajes (Encabezado) ... campos ... tamaño ... significado ... valores posibles" | Recomendado | E §4.2, §4.5 | | Diseñado |
| R8d | "Reglas de Procedimiento ... algoritmos y las máquinas de estado" | Recomendado | E §7, §9 | | Diseñado |
| R8e | "Ejemplos de Implementación ... diagramas de secuencia" | Recomendado | E §14; D:secuencia-*.mmd | | Diseñado |
| R9 | "integrar a la arquitectura de red TCP/IP a través de la API de sockets ... Usted decide qué tipo de protocolo de transporte" | Exigido | P §10; E §2.3 | Código con `socket`, `bind`, `listen`, `accept`, `recvfrom` | Diseñado, F2 |
| R10 | "soportar múltiples clientes simultáneos solicitando y recibiendo información ... se permite el uso de hilos" | Exigido | P §14; E §10 | Prueba concurrente | Diseñado, F3 |
| R11 | "control de excepciones ... conexiones fallidas, mensajes con formato incorrecto y demás situaciones" | Exigido | P §11; E §6, §7.9 | Batería de pruebas de error | Diseñado, F3 |

## 3. Detalles de implementación

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| D1 | "La aplicación de los clientes puede estar escrita en un lenguaje diferente al del servidor" | Permitido | P §5 (Python) | Código en `nodo/` y `cliente/` | Diseñado, F2 |
| D2 | "El cliente puede tener una interfaz gráfica (puede ser sencilla)" | Recomendado | P §5 (Tkinter); E §9.4 | Captura de la ventana | Diseñado, F2 |
| D3 | "La aplicación del servidor sólo puede estar implementado en C" | Exigido | P §5 | Código en `servidor/` | Diseñado, F2 |
| D4 | "No se debe utilizar una API diferente a la de Berkeley para construir los sockets" | Exigido | P §12 (aclaración sobre `libldap`); E §10 | Revisión del código | Diseñado; `libldap` por confirmar |
| D5 | "logging, que muestre en consola las peticiones entrantes y las respuestas enviadas ... almacenarse también en un archivo de logs" | Exigido | P §15; E §11 | Consola y archivo durante la demostración | Diseñado, F2 |
| D6 | "ejecutar recibiendo los parámetros por consola 'puerto' y 'archivoDeLogs'" | Exigido | P §15; E §11 | `./servidor 5050 servidor.log` | Diseñado, F2 |
| D7 | "Las peticiones y respuestas deben almacenar el identificador de cada cliente (ip y puerto origen de la petición)" | Exigido | E §11 (formato de línea) | Archivo de log | Diseñado, F2 |
| D8 | "compilación del código del servidor utilizando gcc y la generación de un archivo Makefile" | Recomendado | P §17.3 | `make clean && make` | Diseñado, F2 |
| D9 | "El servidor puede ser implementado en un servicio en nube" | Opcional | P §3.2; E §15 | No aplica por ahora | Decisión: VirtualBox |

## 4. Selección del protocolo de transporte

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| T1 | "frecuencia de transmisión" | Exigido | P §10.1 | | Diseñado |
| T2 | "tamaño de los mensajes" | Exigido | P §10.1 (tamaños medidos sobre los ejemplos) | | Diseñado |
| T3 | "criticidad de la información" | Exigido | P §10.1 | | Diseñado |
| T4 | "tolerancia a pérdidas" | Exigido | P §10.1 | | Diseñado |
| T5 | "necesidad de orden" | Exigido | P §10.1 | | Diseñado |
| T6 | "necesidad de confiabilidad" | Exigido | P §10.1 | | Diseñado |
| T7 | "necesidad de mantener una conexión" | Exigido | P §10.1 | | Diseñado |
| T8 | "comportamiento ante retardos" | Exigido | P §10.1 | | Diseñado |
| T9 | "comportamiento ante pérdida de mensajes" | Exigido | P §10.1 | | Diseñado |
| T10 | "la decisión deberá estar técnicamente justificada" | Exigido | P §10.2 a §10.5, §18 | | Diseñado |
| T11 | "confirmación de recepción" (si se usa UDP con algún nivel de confiabilidad) | Exigido cuando corresponda | P §10.2 (no se usa en telemetría, con justificación); `ACK` de eventos por TCP en P §10.3 | | Diseñado |
| T12 | "identificación de mensajes" | Exigido cuando corresponda | `session`, `seq` (E §7.3) | Log con descartes | Diseñado, F2 |
| T13 | "temporizadores" | Exigido cuando corresponda | Watchdog (E §7.8, §8) | Nodo detenido pasa a `SIN_REPORTE` | Diseñado, F3 |
| T14 | "retransmisión" | Exigido cuando corresponda | P §10.2 (no se usa, con justificación) | | Diseñado |
| T15 | "detección de duplicados" | Exigido cuando corresponda | `seq` repetido (E §7.3) | Contador `dups` | Diseñado, F3 |
| T16 | "control de mensajes fuera de orden" | Exigido cuando corresponda | `seq` atrasado (E §7.3) | Contador `ooo` | Diseñado, F3 |
| T17 | "No se espera que los estudiantes vuelvan a implementar TCP" | Exigido | P §10.3, §10.5 | | Diseñado |

## 5. Fase 2: comunicación básica

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| F2.1 | "creación y configuración de los sockets" | Exigido | P §17.1; E §10 | Código y demostración | Diseñado, F2 |
| F2.2 | "establecimiento de la comunicación" | Exigido | E §7.1, §7.2, §7.5 | Captura del saludo TCP y del `REGISTER` | Diseñado, F2 |
| F2.3 | "envío de mensajes" | Exigido | E §4.3, §4.4 | Captura | Diseñado, F2 |
| F2.4 | "recepción de mensajes" | Exigido | E §4.3 (encuadre), §4.4 | Prueba con mensajes partidos y pegados | Diseñado, F2 |
| F2.5 | "interpretación de mensajes" | Exigido | E §4.2, §4.5, §6.1 | Pruebas del parser | Diseñado, F2 |
| F2.6 | "construcción de respuestas" | Exigido | E §5 | Log | Diseñado, F2 |
| F2.7 | "implementación de las reglas básicas del protocolo" | Exigido | P §8; E §7 | Demostración | Diseñado, F2 |
| F2.8 | "observar claramente la relación entre la especificación del protocolo y el código" | Exigido | E (nombres de tipos, campos y códigos que se usarán tal cual en el código) | Revisión cruzada código contra especificación | Diseñado, F2 |

## 6. Fase 3: concurrencia, resiliencia y pruebas

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| F3.1 | "el servidor podrá atender múltiples clientes o nodos de manera concurrente" | Exigido | P §14; E §10 | Prueba con varios clientes y nodos | Diseñado, F3 |
| F3.2 | "estrategia de concurrencia ... justificar técnicamente su decisión" | Exigido | P §14 | | Diseñado |
| F3.3 | "mensajes con formato incorrecto" | Exigido | P §11; E §6 (400, 413) | Pruebas con `nc` | Diseñado, F3 |
| F3.4 | "parámetros inválidos" | Exigido | P §11; E §6 (422) | Pruebas con `nc` | Diseñado, F3 |
| F3.5 | "desconexiones" | Exigido | E §7.7; D:fsm-servidor-nodo | Matar un nodo y un cliente | Diseñado, F3 |
| F3.6 | "fallas en la comunicación" | Exigido | E §7.9; D:secuencia-servicios-caidos | Apagar servidor, DNS y LDAP | Diseñado, F3 |
| F3.7 | "nodos desconocidos" | Exigido | E §6 (404 `NODO`, `SESION`) | Pruebas | Diseñado, F3 |
| F3.8 | "expiración de temporizadores" | Exigido | E §8 | Pruebas de `T_ident`, `T_ack` y watchdog | Diseñado, F3 |
| F3.9 | "pérdida de mensajes, cuando corresponda" | Exigido | E §7.3, §7.4 | Pérdida simulada (por ejemplo con `tc netem`) | Diseñado, F3 |
| F3.10 | "duplicación de mensajes, cuando corresponda" | Exigido | E §7.3, §7.4; D:secuencia-evento | Reenvío forzado de un `EVENT` | Diseñado, F3 |
| F3.11 | "El comportamiento esperado ante cada situación deberá estar definido tanto en la especificación del protocolo como en la implementación" | Exigido | E §6, §7, §8, §9 | Implementación coherente | Diseñado en especificación; implementación en F3 |

## 7. Evaluación y entrega

| ID | Requisito exacto del enunciado | Origen | Sección | Evidencia futura | Estado |
|---|---|---|---|---|---|
| G1 | "Implementación de la API de Sockets (5%) ... crear, enlazar y poner a la escucha un socket" | Rúbrica | E §10 | Código | Diseñado, F2 |
| G2 | "Manejo de Múltiples Clientes (10%) ... sin bloquearse" | Rúbrica | P §14 | Prueba concurrente | Diseñado, F3 |
| G3 | "Lógica del Protocolo (25%)" | Rúbrica | E completo | Pruebas por mensaje | Diseñado, F2 y F3 |
| G4 | "Conexión y Petición (15%)" de los clientes | Rúbrica | E §9.1, §9.4 | Nodo y cliente funcionando | Diseñado, F2 |
| G5 | "Manejo de Respuestas (15%) ... incluyendo mensajes de éxito y de error" | Rúbrica | E §9.4 (cliente muestra errores) | Capturas del cliente | Diseñado, F2 y F3 |
| G6 | "Robustez del Protocolo (10%)" | Rúbrica | P §11 | Pruebas de error | Diseñado, F3 |
| G7 | "Coordinación de Mensajes (10%)" | Rúbrica | E §7, D:secuencia-*.mmd | Capturas Wireshark | Diseñado, F2 y F3 |
| G8 | "Especificación del Protocolo (10%)" | Rúbrica | E completo | Este repositorio | Diseñado |
| G9 | "El proyecto debe ser desarrollado en equipos. No debe ser desarrollado de manera individual" | Exigido | P §3.4 | | Por confirmar: el proyecto lo desarrolla una sola persona; se debe aclarar con el profesor |
| G10 | "Cree un repositorio de su proyecto ... evolución progresiva del proyecto durante las diferentes fases" | Exigido | Repositorio `monitoreo-telematica` | Historial de commits por fase | En curso |
| G11 | "proporcionar el enlace al repositorio en el buzón de interactiva virtual" | Exigido | No aplica a la documentación | Comprobante de envío | Pendiente |
| G12 | "se revisará que no haya commits posteriores a esa fecha" | Exigido | P §3.4 (plazo de Fase 1 extendido al 4 de octubre de 2026) | Fechas reales de los commits | Por confirmar las fechas de las fases siguientes |
| G13 | "sustentación ... explicar de forma clara, precisa y concisa el funcionamiento de su código y las decisiones de diseño" | Exigido | `docs/entrega1/exposicion.md` (banco de preguntas); P §18 | Sustentación | Preparación iniciada |

## 8. Decisiones propias que otros requisitos necesitan

Estas no aparecen en el enunciado, pero sin ellas algún requisito quedaría incompleto.

| ID | Decisión | Requisito que la necesita | Sección |
|---|---|---|---|
| X1 | Límite de 512 bytes y conjunto de caracteres seguros | R8 (especificación implementable), R11 | E §4.2 |
| X2 | Encuadre por `\n` sobre TCP | F2.4 (recepción de mensajes sobre un flujo de bytes) | E §4.3 |
| X3 | `session` en la telemetría | R3b, F3.7 (distinguir nodos desconocidos o sesiones viejas) | E §7.3 |
| X4 | `msg_id` con hora de arranque y `ACK` con `dup` | R3c, F3.10 | E §7.4 |
| X5 | Estado `SIN_REPORTE` tras 3 periodos | R3d, F3.8 | E §7.8 |
| X6 | Backoff común de 1 a 30 s | R4b, F3.6 | E §7.9 |
| X7 | Orden de validación de errores | R8, F3.11 (comportamiento definido) | E §6.1 |
| X8 | Límites de conexiones, nodos, intentos y errores seguidos | R11, F3.1 | E §8 |
| X9 | Un solo puerto para TCP y UDP, identificación por primer mensaje | D6 (un solo parámetro de puerto) | P §4.2; E §7.1 |
