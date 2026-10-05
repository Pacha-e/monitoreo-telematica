# MCD/1.0: Protocolo de Monitoreo y Control Distribuido

Especificación del protocolo de aplicación del proyecto "Sistema de monitoreo y control distribuido".

| Dato | Valor |
|---|---|
| Curso | ST0255 Telemática, Universidad EAFIT, 2026-2 |
| Autor | Emmanuel Hernández |
| Versión del documento | 1.0, borrador de diseño (Fase 1) |
| Fecha | 4 de octubre de 2026 |
| Estado | Diseño. Nada de lo descrito aquí está implementado todavía. |

La estructura sigue, a grandes rasgos, la del RFC 793 que sugiere el enunciado: visión general, especificación del servicio, formato de mensajes, reglas de procedimiento y ejemplos. La propuesta de la Fase 1 (`docs/entrega1/propuesta.md`) explica el porqué de las decisiones; este documento es la referencia para implementar. Si una persona distinta al autor quiere escribir un servidor, un nodo o un cliente compatible, esto es lo que debe leer.

## Contenido

1. Convenciones
2. Visión general del protocolo
3. Especificación del servicio
4. Formato de los mensajes
5. Vocabulario
6. Códigos de error
7. Reglas de procedimiento
8. Temporizadores y límites
9. Máquinas de estado
10. Concurrencia del servidor
11. Registro de actividad (logging)
12. Resolución de nombres
13. Consideraciones de seguridad
14. Ejemplos
15. Aspectos abiertos

---

## 1. Convenciones

- "Debe" y "no debe" indican una obligación. Una implementación que no la cumpla no es compatible con MCD/1.0.
- "Debería" indica una recomendación fuerte; se puede ignorar solo con una razón concreta.
- "Puede" indica algo opcional.
- Los mensajes se muestran sin el salto de línea final. En la red, todo mensaje termina en el byte `0x0A` (LF), escrito aquí como `\n` cuando hace falta mostrarlo.
- "Octeto" y "byte" significan lo mismo: 8 bits.
- `P` es el número de puerto que recibe el servidor por consola. En los ejemplos se usa `5050`.
- Las direcciones IP que aparecen en los ejemplos de log son de la red host-only de VirtualBox (`192.168.56.0/24`) y solo ilustran lo que el servidor escribirá en tiempo de ejecución. Ningún programa del proyecto debe tener una IP escrita en su código.

## 2. Visión general del protocolo

### 2.1 Propósito

MCD/1.0 permite que varios nodos reporten su estado a un servidor central y que clientes de administración autenticados consulten ese estado. Cubre las siete operaciones mínimas que pide el enunciado: registro de un nodo, envío periódico de estado, envío de eventos, confirmaciones, consultas, respuestas a consultas y reporte de errores.

### 2.2 Modelo

Es un protocolo cliente-servidor. El servidor central es el único que escucha; los nodos y los clientes de administración siempre inician la comunicación. Los nodos y los clientes nunca se comunican entre sí.

| Entidad | Papel en MCD/1.0 | Implementación prevista |
|---|---|---|
| Servidor central | Escucha en el puerto `P` por TCP y por UDP. Registra nodos, guarda estado e historial, autentica usuarios y responde consultas. | C, sockets Berkeley, `pthread` |
| Nodo | Se registra por TCP, envía telemetría por UDP y eventos por TCP. | Python |
| Cliente de administración | Se autentica y consulta por TCP. | Python con Tkinter |

Servicios externos que el servidor usa pero que no hablan MCD/1.0:

- DNS (BIND9, zona `monitoreo.lab`): todos los componentes resuelven nombres con `getaddrinfo`.
- LDAP (OpenLDAP): el servidor valida credenciales de usuarios y de nodos, y obtiene el perfil del usuario.

### 2.3 Ubicación en la arquitectura TCP/IP

MCD/1.0 es un protocolo de la capa de aplicación. Usa los dos servicios de transporte de la API de sockets Berkeley:

| Canal | Socket | Uso |
|---|---|---|
| TCP, puerto `P` | `SOCK_STREAM` | Registro, eventos, autenticación, consultas, errores y cierre |
| UDP, puerto `P` | `SOCK_DGRAM` | Solo telemetría (y el error 404 que el servidor devuelve a una telemetría con sesión inválida) |

TCP y UDP tienen espacios de puertos independientes, así que el servidor puede abrir ambos sockets en el mismo número `P` sin conflicto. Por eso basta con el único parámetro de puerto que exige el enunciado.

### 2.4 Representación

Los mensajes son texto ASCII de una sola línea, con campos `clave=valor` separados por `|`. Se eligió texto porque se puede probar con `nc`, se lee directamente en Wireshark y sigue la misma idea de HTTP y SMTP vistos en el curso. La propuesta discute la alternativa binaria.

## 3. Especificación del servicio

Las primitivas son las operaciones que cada usuario del protocolo puede pedir. Cada una se traduce en uno o más mensajes de la sección 5.

### 3.1 Primitivas del nodo

| Primitiva | Mensajes | Transporte | Resultado |
|---|---|---|---|
| `REGISTRAR(node_id, secret, kind, period)` | `REGISTER` → `REGISTER_OK` o `ERROR` | TCP | El nodo obtiene una sesión y queda `ACTIVO` en el servidor |
| `REPORTAR(métricas)` | `TELEMETRY` | UDP | Sin confirmación. El servidor actualiza el estado si el datagrama es válido y nuevo |
| `NOTIFICAR_EVENTO(nivel, evento, valor)` | `EVENT` → `ACK` o `ERROR` | TCP | El servidor guarda el evento una sola vez y lo confirma |
| `DESCONECTAR()` | `BYE` → `BYE` | TCP | El servidor marca el nodo `DESCONECTADO` e invalida la sesión |

### 3.2 Primitivas del cliente de administración

| Primitiva | Mensajes | Perfil requerido | Resultado |
|---|---|---|---|
| `AUTENTICAR(user, password)` | `LOGIN` → `LOGIN_OK` o `ERROR` | ninguno | Sesión autenticada con perfil `admin` u `operador` |
| `LISTAR_NODOS()` | `LIST` → `RESPONSE` + `ITEM`* | `admin`, `operador` | Estado resumido de todos los nodos conocidos |
| `CONSULTAR_ESTADO(node_id)` | `STATUS` → `RESPONSE` + `ITEM` | `admin`, `operador` | Último estado del nodo y contadores de telemetría |
| `CONSULTAR_HISTORIAL(node_id, n)` | `HISTORY` → `RESPONSE` + `ITEM`* | `admin`, `operador` | Hasta `n` muestras recientes (máximo 10) |
| `CONSULTAR_EVENTOS(n, node_id?)` | `EVENTS` → `RESPONSE` + `ITEM`* | `admin` | Hasta `n` eventos recientes (máximo 20) |
| `CERRAR()` | `BYE` → `BYE` | cualquiera | Cierre ordenado de la conexión |

### 3.3 Servicio que presta el servidor

- Mantiene una tabla de nodos con estado `ACTIVO`, `SIN_REPORTE` o `DESCONECTADO`.
- Guarda por nodo las últimas 10 muestras de telemetría (el enunciado pide al menos 5 datos históricos).
- Guarda los últimos 100 eventos del sistema, incluidos los que él mismo genera cuando un nodo deja de reportar o se recupera.
- Registra en consola y en archivo cada mensaje recibido y enviado, con la IP y el puerto de origen.

## 4. Formato de los mensajes

### 4.1 Estructura general

```
MCD/1.0|TIPO|clave=valor|clave=valor|...\n
```

- El primer elemento es siempre la versión `MCD/1.0`.
- El segundo es el tipo del mensaje, en mayúsculas.
- Después vienen cero o más campos `clave=valor`.
- El mensaje termina en un único `\n`.

No hay cuerpo aparte ni encabezado de longitud: el `\n` delimita el mensaje. Cada mensaje cabe en 512 bytes, contando el `\n`.

### 4.2 Gramática (ABNF, RFC 5234)

```abnf
mensaje   = version SEP tipo *( SEP campo ) LF
version   = %s"MCD/1.0"                       ; sensible a mayúsculas (RFC 7405)
SEP       = %x7C                              ; "|"
tipo      = 1*16( %x41-5A / %x5F )            ; A-Z y "_"
campo     = clave "=" valor
clave     = %x61-7A *15( %x61-7A / DIGIT / %x5F )   ; empieza por a-z; a-z, 0-9, "_"
valor     = 1*64seguro
seguro    = ALPHA / DIGIT / "." / "-" / "_" / ":"
LF        = %x0A
```

`ALPHA` y `DIGIT` son las reglas básicas de RFC 5234 (letras ASCII `A-Z`, `a-z` y dígitos `0-9`).

Restricciones que la gramática no expresa y que también son obligatorias:

| Regla | Límite |
|---|---|
| Longitud total del mensaje, incluido el `\n` | 512 bytes como máximo |
| Número de campos | 16 como máximo |
| Claves repetidas en un mismo mensaje | No se permiten |
| Orden de los campos | Libre. Se recomienda el orden de las tablas de la sección 5 |
| Campos desconocidos para el tipo | No se permiten en la versión 1.0 |
| Valor vacío (`clave=`) | No se permite |

El conjunto de caracteres seguros excluye a propósito `|`, `=`, espacios, comas, comillas, barras y cualquier byte fuera de ASCII. Así ningún valor puede romper la estructura del mensaje, inyectar texto en un DN o un filtro LDAP, ni ensuciar una línea del log. Si en el futuro un campo necesitara texto libre, se debe usar un código enumerado, no texto arbitrario.

### 4.3 Encuadre (framing) sobre TCP

TCP entrega un flujo de bytes, no mensajes. Un `recv()` puede traer medio mensaje, un mensaje exacto o varios mensajes pegados. Por eso el receptor:

1. Mantiene un buffer por conexión de al menos 1024 bytes.
2. Agrega al buffer lo que entregue cada `recv()`.
3. Mientras el buffer contenga un `\n`, extrae la línea hasta ese `\n` inclusive y la procesa como un mensaje.
4. Si la línea extraída mide más de 512 bytes, o si el buffer acumula 512 bytes sin ningún `\n`, responde `ERROR` 413 y cierra la conexión. No intenta resincronizarse.
5. Si la línea termina en `\r\n`, debe eliminar el `\r` antes de validar. Los emisores no deben enviar `\r`; esta tolerancia existe solo para facilitar pruebas manuales.
6. Una línea vacía se ignora sin respuesta.

El emisor debe enviar el mensaje completo; si `send()` escribe menos bytes de los pedidos, debe volver a llamar `send()` con el resto.

### 4.4 Datagramas sobre UDP

- Cada datagrama contiene exactamente un mensaje completo, terminado en `\n`.
- El receptor debe leer con un buffer mayor a 512 bytes (por ejemplo, 1024) para poder detectar datagramas demasiado grandes.
- Un datagrama de más de 512 bytes, sin `\n` final, con más de un `\n` o que no cumpla la gramática se descarta y se registra en el log. El servidor no responde a estos datagramas.
- El único tipo aceptado por UDP es `TELEMETRY`. Cualquier otro tipo recibido por UDP se descarta y se registra.

Con 512 bytes de mensaje, 8 de encabezado UDP y 20 de encabezado IPv4, un datagrama mide como máximo 540 bytes. Cabe en cualquier MTU de Ethernet sin fragmentación IP.

### 4.5 Definición de campos

Todos los campos usan solo caracteres seguros. La columna "Tamaño" es la longitud del valor en caracteres.

| Campo | Formato | Tamaño | Valores permitidos | Usado en |
|---|---|---|---|---|
| `req` | Entero decimal sin ceros a la izquierda | 1 a 9 | 1 a 999999999 en peticiones; 0 solo en `ERROR` cuando no se pudo leer el `req` original | Todos los mensajes TCP |
| `node_id` | Empieza por `a-z`; sigue `a-z`, `0-9` o `-` | 3 a 32 | Debe existir como `cn` en `ou=devices` del LDAP | `REGISTER`, `REGISTER_OK`, `TELEMETRY`, `EVENT`, `ACK`, `STATUS`, `HISTORY`, `EVENTS`, `ITEM` |
| `secret` | Caracteres seguros | 8 a 64 | Clave del nodo en LDAP | `REGISTER` |
| `kind` | Enumerado | | `SENSOR`, `RED`, `IOT`, `OTRO` | `REGISTER`, `ITEM` |
| `period` | Entero | 1 a 2 | 1 a 60 (segundos entre telemetrías) | `REGISTER`, `REGISTER_OK` |
| `session` | Hexadecimal en minúscula | 16 exactos | Generado por el servidor con 64 bits aleatorios | `REGISTER_OK`, `TELEMETRY` |
| `seq` | Entero | 1 a 10 | 1 a 4294967295 | `TELEMETRY`, `ITEM` |
| `ts` | Entero, segundos desde 1970-01-01 UTC | 1 a 10 | 0 a 9999999999 | `TELEMETRY`, `EVENT`, `ITEM` |
| `cpu` | Decimal con un decimal opcional | 1 a 5 | 0.0 a 100.0 (porcentaje de uso) | `TELEMETRY`, `ITEM` |
| `temp` | Decimal con signo opcional y un decimal opcional | 1 a 5 | -40.0 a 150.0 (grados Celsius) | `TELEMETRY`, `ITEM` |
| `bat` | Entero o `NA` | 1 a 3 | 0 a 100 (porcentaje); `NA` si el equipo no tiene batería | `TELEMETRY`, `ITEM` |
| `opstate` | Enumerado | | `OK`, `DEGRADADO`, `FALLA`, `MANTENIMIENTO` | `TELEMETRY`, `ITEM` |
| `uptime` | Entero | 1 a 10 | 0 a 4294967295 (segundos encendido) | `TELEMETRY`, `ITEM` |
| `msg_id` | `<arranque>-<contador>` | 3 a 20 | `arranque`: segundos epoch en que inició el proceso del nodo (1 a 10 dígitos). `contador`: 1 a 999999999. En `ITEM` también puede valer `srv-<n>` para eventos generados por el servidor | `EVENT`, `ACK`, `ITEM` |
| `level` | Enumerado | | `INFO`, `ADVERTENCIA`, `CRITICO` | `EVENT`, `ITEM` |
| `event` | Enumerado | | `FALLA`, `UMBRAL_TEMP`, `UMBRAL_CPU`, `BATERIA_BAJA`, `CAMBIO_ESTADO`, `ALARMA`, `CONECTIVIDAD` | `EVENT`, `ITEM` |
| `value` | Caracteres seguros | 1 a 32 | Dato asociado al evento: una medida (`85.2`) o un estado (`FALLA`) | `EVENT`, `ITEM` |
| `dup` | Entero | 1 | 0 = evento nuevo, 1 = evento ya recibido antes | `ACK` |
| `user` | Empieza por `a-z`; sigue `a-z`, `0-9`, `.`, `-` o `_` | 3 a 32 | Debe existir como `uid` en `ou=people` del LDAP | `LOGIN`, `LOGIN_OK` |
| `password` | Caracteres seguros | 8 a 64 | Clave del usuario en LDAP | `LOGIN` |
| `role` | Enumerado | | `admin`, `operador` | `LOGIN_OK` |
| `n` | Entero | 1 a 2 | `HISTORY`: 1 a 10. `EVENTS`: 1 a 20 | `HISTORY`, `EVENTS` |
| `op` | Enumerado | | `LIST`, `STATUS`, `HISTORY`, `EVENTS` | `RESPONSE` |
| `items` | Entero | 1 a 3 | 0 a 100 | `RESPONSE` |
| `idx` | Entero | 1 a 3 | 1 a `items` | `ITEM` |
| `state` | Enumerado | | `ACTIVO`, `SIN_REPORTE`, `DESCONECTADO` | `ITEM` |
| `last_seen` | Entero, segundos epoch del servidor | 1 a 10 | Hora de registro hasta que llegue la primera telemetría; después, hora de la última muestra aceptada | `ITEM` |
| `lost` | Entero | 1 a 10 | Estimado de telemetrías perdidas en la sesión | `ITEM` |
| `dups` | Entero | 1 a 10 | Telemetrías duplicadas descartadas en la sesión | `ITEM` |
| `ooo` | Entero | 1 a 10 | Telemetrías atrasadas (fuera de orden) descartadas en la sesión | `ITEM` |
| `code` | Entero de 3 dígitos | 3 | Ver sección 6 | `ERROR` |
| `reason` | Enumerado | | Ver sección 6 | `ERROR` |
| `field` | Nombre de una clave | 1 a 16 | Campo que causó un error 422 | `ERROR` |

En las respuestas del servidor, `cpu`, `temp`, `bat`, `opstate`, `uptime` y `seq` valen `NA` cuando el nodo todavía no ha enviado ninguna telemetría válida en la sesión actual.

## 5. Vocabulario

En las tablas, "O" significa obligatorio y "P" opcional. La columna "Dirección" usa N para nodo, C para cliente de administración y S para servidor.

### 5.1 Resumen

| Tipo | Dirección | Transporte | Operación del enunciado (requisito 7) | Respuesta esperada |
|---|---|---|---|---|
| `REGISTER` | N → S | TCP | a) registro de un nodo | `REGISTER_OK` o `ERROR` |
| `REGISTER_OK` | S → N | TCP | d) confirmación | |
| `TELEMETRY` | N → S | UDP | b) información periódica de estado | Ninguna (salvo `ERROR` 404) |
| `EVENT` | N → S | TCP | c) envío de un evento | `ACK` o `ERROR` |
| `ACK` | S → N | TCP | d) confirmación | |
| `LOGIN` | C → S | TCP | e) consulta (requisito previo de acceso) | `LOGIN_OK` o `ERROR` |
| `LOGIN_OK` | S → C | TCP | d) confirmación | |
| `LIST` | C → S | TCP | e) consulta de información | `RESPONSE` + `ITEM` |
| `STATUS` | C → S | TCP | e) consulta de información | `RESPONSE` + `ITEM` |
| `HISTORY` | C → S | TCP | e) consulta de información | `RESPONSE` + `ITEM` |
| `EVENTS` | C → S | TCP | e) consulta de información | `RESPONSE` + `ITEM` |
| `RESPONSE` | S → C | TCP | f) respuesta a una consulta | |
| `ITEM` | S → C | TCP | f) respuesta a una consulta | |
| `ERROR` | S → N, S → C | TCP; UDP solo para 404 | g) reporte de errores | |
| `BYE` | N → S, C → S, S → N, S → C | TCP | d) confirmación de cierre | `BYE` |

Solo el servidor emite `ERROR`. Si un nodo o un cliente recibe un mensaje inválido del servidor, lo registra en su log local, cierra la conexión y aplica el procedimiento de reintento de la sección 7.9.

### 5.2 REGISTER

Lo envía el nodo como primer mensaje de una conexión TCP nueva.

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | Identificador de la petición |
| `node_id` | O | Nombre del nodo |
| `secret` | O | Clave del nodo |
| `kind` | O | Tipo de equipo |
| `period` | O | Segundos entre telemetrías que el nodo se compromete a enviar |

```
MCD/1.0|REGISTER|req=1|node_id=nodo-01|secret=clave-de-ejemplo|kind=SENSOR|period=5
```

### 5.3 REGISTER_OK

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | Copia del `req` de `REGISTER` |
| `node_id` | O | Copia del `node_id` |
| `session` | O | Token de la sesión, necesario en cada `TELEMETRY` |
| `period` | O | Periodo aceptado (igual al pedido) |

```
MCD/1.0|REGISTER_OK|req=1|node_id=nodo-01|session=4f9c2a7d1e0b8c63|period=5
```

### 5.4 TELEMETRY

Datagrama UDP enviado cada `period` segundos al puerto `P` del servidor.

| Campo | O/P | Descripción |
|---|---|---|
| `node_id` | O | Nombre del nodo |
| `session` | O | Token recibido en `REGISTER_OK` |
| `seq` | O | Número de secuencia; empieza en 1 en cada sesión y aumenta de a 1 |
| `ts` | O | Hora del nodo al tomar la muestra |
| `cpu` | O | Uso de CPU |
| `temp` | O | Temperatura |
| `bat` | O | Nivel de batería o `NA` |
| `opstate` | O | Estado operativo informado por el nodo |
| `uptime` | O | Tiempo encendido |

```
MCD/1.0|TELEMETRY|node_id=nodo-01|session=4f9c2a7d1e0b8c63|seq=41|ts=1791126131|cpu=37.5|temp=48.1|bat=91|opstate=OK|uptime=3731
```

`TELEMETRY` no lleva `req` porque no tiene respuesta. La "disponibilidad" que menciona el enunciado no la informa el nodo: la calcula el servidor a partir de si la telemetría sigue llegando (estado `ACTIVO` o `SIN_REPORTE`).

### 5.5 EVENT

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | Identificador de la petición en esta conexión |
| `node_id` | O | Debe coincidir con el nodo registrado en la conexión |
| `msg_id` | O | Identidad del evento; se conserva igual en cada reintento |
| `ts` | O | Hora del nodo cuando ocurrió el evento |
| `level` | O | Gravedad |
| `event` | O | Tipo de evento |
| `value` | P | Dato asociado |

```
MCD/1.0|EVENT|req=7|node_id=nodo-01|msg_id=1791122400-7|ts=1791126146|level=CRITICO|event=UMBRAL_TEMP|value=85.2
```

`req` y `msg_id` cumplen papeles distintos. `req` correlaciona una petición con su respuesta dentro de una conexión. `msg_id` identifica el evento en sí y no cambia aunque el nodo lo reenvíe por otra conexión, después de reconectarse.

### 5.6 ACK

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | Copia del `req` del `EVENT` |
| `node_id` | O | Copia |
| `msg_id` | O | Copia |
| `dup` | O | 0 si el evento se guardó ahora; 1 si ya estaba guardado |

```
MCD/1.0|ACK|req=7|node_id=nodo-01|msg_id=1791122400-7|dup=0
```

### 5.7 LOGIN y LOGIN_OK

`LOGIN` lo envía el cliente como primer mensaje de una conexión TCP nueva.

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | Identificador de la petición |
| `user` | O | Usuario LDAP |
| `password` | O | Clave del usuario |

```
MCD/1.0|LOGIN|req=1|user=operador1|password=clave-de-ejemplo
```

| Campo de `LOGIN_OK` | O/P | Descripción |
|---|---|---|
| `req` | O | Copia |
| `user` | O | Copia |
| `role` | O | Perfil obtenido del LDAP |

```
MCD/1.0|LOGIN_OK|req=1|user=operador1|role=operador
```

### 5.8 Consultas: LIST, STATUS, HISTORY y EVENTS

| Tipo | Campos | Perfil |
|---|---|---|
| `LIST` | `req` (O) | `admin`, `operador` |
| `STATUS` | `req` (O), `node_id` (O) | `admin`, `operador` |
| `HISTORY` | `req` (O), `node_id` (O), `n` (O, 1 a 10) | `admin`, `operador` |
| `EVENTS` | `req` (O), `n` (O, 1 a 20), `node_id` (P, filtra por nodo) | `admin` |

```
MCD/1.0|LIST|req=2
MCD/1.0|STATUS|req=3|node_id=nodo-02
MCD/1.0|HISTORY|req=4|node_id=nodo-01|n=5
MCD/1.0|EVENTS|req=5|n=10
```

### 5.9 RESPONSE e ITEM

La respuesta a cualquier consulta es una línea `RESPONSE` seguida de exactamente `items` líneas `ITEM`. Las líneas `ITEM` llevan el mismo `req` y un `idx` de 1 a `items`, en orden. Si no hay resultados, se envía `RESPONSE` con `items=0` y ninguna línea `ITEM`.

| Campo de `RESPONSE` | O/P | Descripción |
|---|---|---|
| `req` | O | Copia del `req` de la consulta |
| `op` | O | Consulta que se responde |
| `items` | O | Cantidad de líneas `ITEM` que siguen |

Los campos de `ITEM` dependen de `op`. Todos llevan `req` e `idx`.

| `op` | Campos adicionales de cada `ITEM` | Orden |
|---|---|---|
| `LIST` | `node_id`, `kind`, `state`, `last_seen` | Por `node_id` |
| `STATUS` | `node_id`, `state`, `last_seen`, `seq`, `cpu`, `temp`, `bat`, `opstate`, `uptime`, `lost`, `dups`, `ooo` | Un solo ítem |
| `HISTORY` | `node_id`, `seq`, `ts`, `cpu`, `temp`, `bat`, `opstate` | Más reciente primero |
| `EVENTS` | `node_id`, `msg_id`, `ts`, `level`, `event`, `value` (P) | Más reciente primero, según el orden en que el servidor los guardó (el `ts` es el del origen y puede venir de otro reloj) |

```
MCD/1.0|RESPONSE|req=2|op=LIST|items=2
MCD/1.0|ITEM|req=2|idx=1|node_id=nodo-01|kind=SENSOR|state=ACTIVO|last_seen=1791126151
MCD/1.0|ITEM|req=2|idx=2|node_id=nodo-02|kind=RED|state=SIN_REPORTE|last_seen=1791126121
```

El ítem de `STATUS` es el mensaje más largo del protocolo. Con todos los campos en su tamaño máximo ocupa 245 bytes, incluido el salto de línea:

```
MCD/1.0|RESPONSE|req=3|op=STATUS|items=1
MCD/1.0|ITEM|req=3|idx=1|node_id=nodo-02|state=SIN_REPORTE|last_seen=1791126121|seq=118|cpu=12.0|temp=39.4|bat=NA|opstate=DEGRADADO|uptime=86400|lost=2|dups=0|ooo=1
```

Se decidió partir la respuesta en líneas en lugar de meter una lista dentro de un campo. Una lista necesitaría separadores como `,` o `;`, que quedaron fuera del conjunto seguro, y además una respuesta de historial con 10 muestras no cabría en 512 bytes.

### 5.10 ERROR

| Campo | O/P | Descripción |
|---|---|---|
| `req` | O | `req` de la petición que falló, o 0 si no se pudo leer |
| `code` | O | Código numérico (sección 6) |
| `reason` | O | Motivo enumerado (sección 6) |
| `field` | P | Clave del campo culpable, solo con código 422 |

```
MCD/1.0|ERROR|req=4|code=422|reason=VALOR|field=n
```

### 5.11 BYE

Cierre ordenado. Lo envía el nodo o el cliente; el servidor contesta con un `BYE` que copia el `req` y luego cierra la conexión.

```
MCD/1.0|BYE|req=9
```

## 6. Códigos de error

Los códigos siguen la idea de los códigos de estado de HTTP vistos en clase: el primer dígito agrupa (4 = problema de quien envía, 5 = problema del servidor o de un servicio que él usa).

| Código | `reason` | Cuándo ocurre | Qué hace el servidor | Qué debe hacer quien lo recibe |
|---|---|---|---|---|
| 400 | `FORMATO` | La línea no cumple la gramática de 4.2 | Responde y mantiene la conexión | Corregir el mensaje; no reenviarlo igual |
| 400 | `VERSION` | La versión no es `MCD/1.0` | Responde y mantiene la conexión | Usar `MCD/1.0` |
| 400 | `TIPO` | Tipo de mensaje desconocido, o un tipo que solo emite el servidor (`REGISTER_OK`, `ACK`, `LOGIN_OK`, `RESPONSE`, `ITEM`, `ERROR`) | Responde y mantiene la conexión | No reenviar |
| 401 | `CREDENCIALES` | LDAP rechaza el `user`/`password` o el `node_id`/`secret` | `LOGIN`: cuenta un intento fallido; al tercero cierra. `REGISTER`: responde y cierra | Cliente: pedir de nuevo las credenciales. Nodo: esperar con backoff y reintentar |
| 401 | `SIN_SESION` | Llega una consulta o un `EVENT` antes de `LOGIN_OK` o `REGISTER_OK` | Responde y mantiene la conexión | Autenticarse o registrarse primero |
| 403 | `ROL` | El perfil no permite la operación (un `operador` pide `EVENTS`, un nodo consulta, un cliente envía `EVENT`) o el usuario autenticado no pertenece a ningún grupo de perfil | Responde. En `LOGIN` cuenta como intento fallido | No repetir la operación |
| 403 | `NODO_AJENO` | El `node_id` de un `EVENT` no es el nodo registrado en esa conexión | Responde y mantiene la conexión | Corregir; es un error de programación del nodo |
| 404 | `NODO` | `STATUS`, `HISTORY` o `EVENTS` nombran un nodo que no está en la tabla; o llega `TELEMETRY` de un nodo desconocido | Responde por TCP; por UDP aplica el límite de 7.3 | Cliente: informar al usuario. Nodo: volver a registrarse |
| 404 | `SESION` | `TELEMETRY` con un `session` que no es el vigente para ese nodo | Responde por UDP con el límite de 7.3 y descarta el datagrama | Cerrar la conexión TCP y registrarse de nuevo |
| 408 | `TIEMPO` | Venció `T_ident` o `T_inactividad` (sección 8) | Responde y cierra | Reconectarse si todavía lo necesita |
| 409 | `ESTADO` | `REGISTER` o `LOGIN` en una conexión que ya se identificó | Responde y mantiene la conexión | Abrir otra conexión si de verdad quiere otra identidad |
| 409 | `TRANSPORTE` | Llega `TELEMETRY` por TCP | Responde y mantiene la conexión | Enviar la telemetría por UDP |
| 413 | `TAMANO` | Más de 512 bytes sin `\n` | Responde y cierra la conexión | Reconectarse y enviar mensajes válidos |
| 422 | `FALTA_CAMPO` | Falta un campo obligatorio | Responde con `field` | Corregir |
| 422 | `CAMPO_DESCONOCIDO` | Hay un campo que no corresponde al tipo | Responde con `field` | Corregir |
| 422 | `CAMPO_REPETIDO` | Una clave aparece dos veces | Responde con `field` | Corregir |
| 422 | `VALOR` | Un valor está fuera de rango, no pertenece al enumerado o no tiene el formato del campo | Responde con `field` | Corregir |
| 500 | `INTERNO` | Falla inesperada en el servidor (por ejemplo, sin memoria) | Responde si puede, registra y cierra esa conexión. El proceso sigue | Reconectarse con backoff |
| 503 | `LDAP` | El servidor LDAP no responde o rechaza la conexión | Responde y mantiene la conexión. Entra en espera de reintento (7.9) | Reintentar más tarde; no cuenta como intento fallido |
| 503 | `DNS` | El servidor no pudo resolver el nombre del LDAP | Igual que `LDAP` | Igual que `LDAP` |
| 503 | `CAPACIDAD` | Se alcanzó el máximo de conexiones o de nodos | Responde y cierra | Esperar con backoff y reintentar |

Un `ERROR` con código 400 o 422 no cierra la conexión, pero el servidor debe cerrarla después de 5 errores de formato (400 o 422) seguidos en la misma conexión. Esto evita que un programa defectuoso mantenga ocupado un hilo enviando basura.

### 6.1 Orden de validación

Para que dos implementaciones respondan el mismo código ante el mismo mensaje, el servidor valida en este orden y responde con el primer fallo que encuentre:

1. Tamaño (413).
2. Gramática general (400 `FORMATO`).
3. Versión (400 `VERSION`).
4. Tipo conocido que el servidor acepta como petición (400 `TIPO`).
5. Canal correcto: `TELEMETRY` solo por UDP (409 `TRANSPORTE`).
6. Estado de la conexión: identificación previa (401 `SIN_SESION`), identificación repetida (409 `ESTADO`), perfil (403 `ROL`).
7. Campos: obligatorios, desconocidos, repetidos y valores (422).
8. Semántica: nodo ajeno (403), nodo o sesión desconocidos (404), credenciales (401), servicios externos (503).

Si no se pudo extraer `req` (pasos 1 a 4, `req` inválido o un tipo que no lleva `req`, como `TELEMETRY`), el `ERROR` lleva `req=0`.

## 7. Reglas de procedimiento

### 7.1 Identificación de una conexión TCP

Nodos y clientes usan el mismo puerto TCP. El servidor sabe qué es cada conexión por su primer mensaje válido:

- `REGISTER` exitoso: la conexión queda como conexión de nodo, ligada a ese `node_id`.
- `LOGIN` exitoso: la conexión queda como sesión de administración con el perfil obtenido.

Mientras no se identifique, la conexión solo acepta `REGISTER`, `LOGIN` y `BYE`. Una consulta o un `EVENT` reciben 401 `SIN_SESION`; una `TELEMETRY` por TCP recibe 409 `TRANSPORTE`, por el orden de validación de 6.1. Una conexión ya identificada no puede cambiar de identidad (409 `ESTADO`).

### 7.2 Registro de un nodo

1. El nodo resuelve el nombre del servidor, abre la conexión TCP y envía `REGISTER`.
2. El servidor valida el mensaje y luego hace un *bind* simple contra LDAP con el DN `cn=<node_id>,ou=devices,dc=monitoreo,dc=lab` y la clave `secret`.
3. Si el LDAP acepta, el servidor:
   - crea la entrada del nodo si no existía, o reutiliza la existente (con su historial);
   - genera un `session` nuevo con 64 bits aleatorios leídos de `/dev/urandom`;
   - pone `last_seq = 0`, `last_seen = ahora` y los contadores `lost`, `dups` y `ooo` en 0;
   - marca el nodo `ACTIVO` y responde `REGISTER_OK`.
4. Si ya existía otra conexión TCP abierta para ese mismo `node_id`, el servidor la cierra después de aceptar el nuevo registro. La sesión anterior deja de ser válida. Esto cubre el caso de un nodo que se reinicia antes de que el servidor note que la conexión vieja murió. La conexión reemplazada ya no es la conexión vigente del nodo, así que su cierre no cambia el estado del nodo.
5. Si el LDAP rechaza, responde 401 `CREDENCIALES` y cierra la conexión. Si el LDAP no está disponible, responde 503 y mantiene la conexión.
6. Si la tabla ya tiene el máximo de nodos y el `node_id` es nuevo, responde 503 `CAPACIDAD` y cierra.

La conexión TCP del nodo queda abierta mientras el nodo funcione. Por ella viajan los eventos y el `BYE`.

### 7.3 Telemetría

El nodo envía un `TELEMETRY` por UDP cada `period` segundos mientras esté registrado. No espera respuesta.

Al recibir un datagrama válido, el servidor busca el nodo y compara `session`:

- Si el nodo no existe: descarta y responde 404 `NODO`.
- Si `session` no es la vigente (por ejemplo, el servidor se reinició o el nodo quedó `DESCONECTADO`): descarta y responde 404 `SESION`.

Para no convertirse en amplificador de tráfico, el servidor envía como máximo un `ERROR` por UDP cada 5 segundos a una misma dirección IP y puerto de origen. Los demás datagramas inválidos solo se registran.

Si la sesión es válida, el servidor compara `seq` con `last_seq` del nodo:

| Caso | Interpretación | Acción |
|---|---|---|
| `seq == last_seq + 1` | Datagrama esperado | Acepta: actualiza el estado, agrega la muestra al historial, `last_seq = seq`, `last_seen = ahora` |
| `seq > last_seq + 1` | Se perdieron `seq - last_seq - 1` datagramas, o vienen atrasados | Acepta igual que el caso anterior y suma la diferencia a `lost` |
| `seq == last_seq` | Duplicado | Descarta, suma 1 a `dups`, registra |
| `seq < last_seq` | Atrasado (llegó fuera de orden) | Descarta, suma 1 a `ooo`, registra |

No hay retransmisión ni reordenamiento: una muestra vieja no aporta nada si ya llegó una más reciente. `lost` es un estimado por exceso, porque un datagrama contado como perdido puede llegar después y quedar contado también en `ooo`. Para el propósito del contador (ver si la red está perdiendo datos) eso es suficiente.

Si el nodo llegara a `seq = 4294967295`, debe registrarse de nuevo para empezar otra sesión. Con un periodo de 1 segundo eso tomaría más de 130 años, así que en la práctica no ocurre.

Si el nodo estaba `SIN_REPORTE` y llega una telemetría aceptada, vuelve a `ACTIVO` y el servidor genera el evento interno `CONECTIVIDAD` con `value=RECUPERADO` y `level=INFO`.

### 7.4 Eventos, confirmación e idempotencia

1. El nodo asigna a cada evento un `msg_id` de la forma `<arranque>-<contador>`. `arranque` es la hora epoch en que inició el proceso del nodo y `contador` empieza en 1 y aumenta con cada evento. Así un nodo que se reinicia no repite identificadores, siempre que su reloj no retroceda.
2. El nodo guarda el evento en una cola local de pendientes (máximo 32). Si la cola se llena, descarta el pendiente más antiguo y lo registra en su log.
3. El nodo envía un solo `EVENT` a la vez y espera el `ACK` durante `T_ack` (5 segundos) antes de enviar el siguiente.
4. El servidor verifica que `node_id` coincida con el nodo de la conexión (si no, 403 `NODO_AJENO`).
5. El servidor busca `(node_id, msg_id)` entre los últimos 64 `msg_id` recibidos de ese nodo:
   - si no está, guarda el evento, lo registra en el log y responde `ACK` con `dup=0`;
   - si ya está, no lo guarda de nuevo y responde `ACK` con `dup=1`.
6. El servidor envía el `ACK` solo después de guardar el evento en memoria y escribirlo en el log. Por eso el `ACK` significa "procesado", no solo "llegó".
7. Si el `ACK` no llega a tiempo o la conexión se cae, el nodo cierra la conexión, se reconecta, se registra otra vez y reenvía el mismo evento con el mismo `msg_id` y un `req` nuevo.
8. Si el servidor responde `ERROR` 400, 403 o 422 a un `EVENT`, el nodo saca ese evento de la cola y lo registra en su log, porque reenviarlo igual produciría el mismo error.

TCP ya garantiza que los bytes llegan en orden y sin duplicados mientras la conexión exista. El `msg_id` cubre el caso que TCP no cubre: un evento que el servidor procesó pero cuyo `ACK` se perdió porque la conexión se cayó en ese momento.

### 7.5 Autenticación y perfiles

1. El cliente abre una conexión TCP y envía `LOGIN`.
2. El servidor hace un *bind* simple con `uid=<user>,ou=people,dc=monitoreo,dc=lab` y `password`.
3. Con esa misma conexión LDAP busca en `ou=groups,dc=monitoreo,dc=lab` los grupos `groupOfNames` que tengan como `member` el DN del usuario:
   - si está en `cn=admins`, el perfil es `admin`;
   - si no, y está en `cn=operadores`, el perfil es `operador`;
   - si no está en ninguno, responde 403 `ROL`.
4. Si todo sale bien, responde `LOGIN_OK` con el perfil.
5. Cada `LOGIN` rechazado (401 `CREDENCIALES` o 403 `ROL`) cuenta como intento fallido. Al tercero, el servidor responde y cierra la conexión. Un 503 no cuenta como intento fallido.

Permisos por perfil:

| Operación | `admin` | `operador` | Conexión de nodo |
|---|---|---|---|
| `LIST`, `STATUS`, `HISTORY` | Sí | Sí | No (403 `ROL`) |
| `EVENTS` | Sí | No (403 `ROL`) | No (403 `ROL`) |
| `EVENT` | No (403 `ROL`) | No (403 `ROL`) | Sí |
| `BYE` | Sí | Sí | Sí |

El servidor no guarda contraseñas. Cada verificación se hace contra LDAP en el momento.

### 7.6 Consultas

- El cliente envía una sola consulta a la vez y espera su respuesta completa (`RESPONSE` y sus `items` líneas `ITEM`) antes de enviar otra.
- El cliente debe comprobar que `req` coincide con el de su consulta y que recibió exactamente `items` líneas `ITEM`. Si no, trata la respuesta como inválida: registra, cierra y reconecta.
- El servidor arma la respuesta completa con una copia de los datos tomada mientras tiene el candado de la tabla y la envía después de soltarlo, para no bloquear a los demás hilos mientras escribe en el socket.

### 7.7 Cierre

- Cierre ordenado: el nodo o el cliente envía `BYE`, el servidor contesta `BYE` y cierra. Si era un nodo, pasa a `DESCONECTADO` y su sesión deja de valer.
- Cierre abrupto: `recv()` devuelve 0 (el otro extremo cerró) o -1 con un error distinto de un vencimiento de tiempo. El servidor libera la conexión y, si era la conexión vigente de un nodo, lo marca `DESCONECTADO`.
- El historial y los eventos de un nodo desconectado se conservan. Si vuelve a registrarse, recupera su entrada.

### 7.8 Watchdog

Un hilo del servidor revisa la tabla cada segundo. Si un nodo `ACTIVO` lleva más de `3 × period` segundos sin telemetría aceptada (medido con el reloj del servidor, no con el `ts` del nodo), pasa a `SIN_REPORTE` y se genera el evento interno `CONECTIVIDAD` con `value=SIN_REPORTE` y `level=ADVERTENCIA`. Los eventos internos usan el `node_id` del nodo afectado y `msg_id=srv-<n>`, con un contador propio del servidor.

Se eligieron tres periodos porque una sola pérdida UDP es normal y no debe disparar una alarma; tres seguidas ya indican un problema real del nodo o de la red.

### 7.9 Reintentos y backoff

Ningún fallo de red, DNS o LDAP termina un proceso. Todos los componentes usan la misma espera creciente:

```
1 s, 2 s, 4 s, 8 s, 16 s, 30 s, 30 s, ...
```

La espera vuelve a 1 s después de un éxito (registro aceptado, sesión iniciada o LDAP disponible otra vez).

| Quién | Qué falla | Qué hace |
|---|---|---|
| Nodo | DNS, `connect()`, `ERROR` 401/503 en registro, `ACK` que no llega, caída de TCP | Registra, espera según el backoff y vuelve a resolver el nombre |
| Nodo | `ERROR` 404 por UDP | Cierra la conexión TCP y vuelve a registrarse sin esperar |
| Cliente | DNS, `connect()`, respuesta que no llega, caída de TCP | Muestra el problema en la ventana, espera y reconecta. Repite `LOGIN` con las credenciales que tiene en memoria |
| Servidor | LDAP o DNS del LDAP | Responde 503 y no vuelve a intentar contactar al LDAP hasta que pase la espera actual. Mientras tanto responde 503 de inmediato |

## 8. Temporizadores y límites

| Nombre | Valor | Dónde | Qué pasa al vencer |
|---|---|---|---|
| `period` | 1 a 60 s (5 s por defecto) | Nodo | Envía la siguiente `TELEMETRY` |
| `T_sin_reporte` | 3 × `period` | Servidor (watchdog) | Nodo pasa a `SIN_REPORTE` |
| `T_ack` | 5 s | Nodo | Cierra TCP, reconecta y reenvía el evento |
| `T_resp` | 5 s | Nodo y cliente | Trata la falta de respuesta como falla de red |
| `T_ident` | 60 s, se reinicia tras cada `LOGIN` fallido | Servidor | `ERROR` 408 y cierre de la conexión no identificada |
| `T_inactividad` | 300 s sin peticiones | Servidor, solo sesiones de administración | `ERROR` 408 y cierre |
| Refresco del cliente | 5 s | Cliente | Envía `LIST` y la consulta de la vista activa |
| Límite de `ERROR` por UDP | 1 cada 5 s por IP:puerto | Servidor | Los siguientes errores solo se registran |
| Backoff | 1, 2, 4, 8, 16, 30 s | Todos | Ver 7.9 |

La conexión TCP de un nodo no tiene temporizador de inactividad, porque los eventos son esporádicos y la vida del nodo se vigila con la telemetría. El servidor debe activar `SO_KEEPALIVE` en todas las conexiones aceptadas para detectar a la larga conexiones medio abiertas.

| Límite | Valor |
|---|---|
| Tamaño máximo de mensaje | 512 bytes con `\n` |
| Campos por mensaje | 16 |
| Conexiones TCP simultáneas | 64 |
| Nodos en la tabla | 32 |
| Muestras de historial por nodo | 10 |
| Eventos guardados en total | 100 |
| `msg_id` recordados por nodo para detectar duplicados | 64 |
| Eventos pendientes en la cola del nodo | 32 |
| Intentos de `LOGIN` por conexión | 3 |
| Errores de formato seguidos por conexión | 5 |

## 9. Máquinas de estado

Los diagramas están en `docs/diagramas/` (fuente Mermaid). Las tablas de esta sección son la versión normativa.

### 9.1 Nodo (`fsm-nodo.mmd`)

| Estado | Evento | Acción | Siguiente |
|---|---|---|---|
| `INICIO` | Arranque | Lee la configuración, fija `arranque` | `RESOLVIENDO` |
| `RESOLVIENDO` | `getaddrinfo` responde | Guarda la dirección del servidor | `CONECTANDO` |
| `RESOLVIENDO` | `getaddrinfo` falla | Registra el error | `ESPERA_REINTENTO` |
| `CONECTANDO` | `connect()` exitoso | Envía `REGISTER`, arranca `T_resp` | `REGISTRANDO` |
| `CONECTANDO` | `connect()` falla | Registra | `ESPERA_REINTENTO` |
| `REGISTRANDO` | `REGISTER_OK` | Guarda `session`, `seq = 0`, backoff a 1 s, arranca `period` | `OPERANDO` |
| `REGISTRANDO` | `ERROR`, vence `T_resp` o se cae TCP | Registra, cierra TCP | `ESPERA_REINTENTO` |
| `OPERANDO` | Vence `period` | `seq + 1`, envía `TELEMETRY` por UDP | `OPERANDO` |
| `OPERANDO` | Hay un evento pendiente | Envía `EVENT`, arranca `T_ack` | `ESPERANDO_ACK` |
| `ESPERANDO_ACK` | Vence `period` | Envía `TELEMETRY` (la telemetría no se detiene) | `ESPERANDO_ACK` |
| `ESPERANDO_ACK` | `ACK` con el `msg_id` esperado | Saca el evento de la cola | `OPERANDO` |
| `ESPERANDO_ACK` | `ERROR` 400, 403 o 422 | Descarta el evento y registra | `OPERANDO` |
| `ESPERANDO_ACK` | Vence `T_ack`, se cae TCP u otro `ERROR` | Cierra TCP; el evento sigue en la cola | `ESPERA_REINTENTO` |
| `OPERANDO` o `ESPERANDO_ACK` | `ERROR` 404 por UDP | Cierra TCP | `RESOLVIENDO` |
| `OPERANDO` | Se cae TCP | Cierra el socket | `ESPERA_REINTENTO` |
| `ESPERA_REINTENTO` | Vence la espera | Duplica la espera hasta 30 s | `RESOLVIENDO` |
| `OPERANDO` | Orden de apagado | Envía `BYE`, arranca `T_resp` | `CERRANDO` |
| `CERRANDO` | `BYE` del servidor o vence `T_resp` | Cierra sockets | `FIN` |

### 9.2 Nodo visto por el servidor (`fsm-servidor-nodo.mmd`)

| Estado | Evento | Acción | Siguiente |
|---|---|---|---|
| `DESCONOCIDO` | `REGISTER` válido y LDAP acepta | Crea la entrada, sesión nueva, `REGISTER_OK` | `ACTIVO` |
| `DESCONOCIDO` | `TELEMETRY` | 404 `NODO` (con límite) | `DESCONOCIDO` |
| `ACTIVO` | `TELEMETRY` aceptada | Actualiza estado e historial | `ACTIVO` |
| `ACTIVO` | `TELEMETRY` duplicada o atrasada | Descarta, cuenta y registra | `ACTIVO` |
| `ACTIVO` | `EVENT` | Guarda si es nuevo, `ACK` | `ACTIVO` |
| `ACTIVO` | `REGISTER` desde otra conexión | Cierra la conexión anterior, sesión nueva | `ACTIVO` |
| `ACTIVO` | Watchdog: más de 3 periodos sin telemetría | Evento interno `CONECTIVIDAD`/`SIN_REPORTE` | `SIN_REPORTE` |
| `SIN_REPORTE` | `TELEMETRY` aceptada | Actualiza; evento interno `CONECTIVIDAD`/`RECUPERADO` | `ACTIVO` |
| `SIN_REPORTE` | `EVENT` | Guarda si es nuevo, `ACK` | `SIN_REPORTE` |
| `SIN_REPORTE` | `REGISTER` desde otra conexión | Cierra la conexión anterior, sesión nueva | `ACTIVO` |
| `ACTIVO` o `SIN_REPORTE` | `BYE`, `recv()` = 0 o error de socket en la conexión vigente del nodo | Invalida la sesión, conserva historial | `DESCONECTADO` |
| `DESCONECTADO` | `TELEMETRY` | 404 `SESION` (con límite) | `DESCONECTADO` |
| `DESCONECTADO` | `REGISTER` válido y LDAP acepta | Sesión nueva, contadores en 0 | `ACTIVO` |

### 9.3 Sesión de administración en el servidor (`fsm-sesion-admin.mmd`)

| Estado | Evento | Acción | Siguiente |
|---|---|---|---|
| (inicio) | `accept()` | Arranca `T_ident`, `fallos = 0` | `CONECTADA` |
| (inicio) | `accept()` con 64 conexiones abiertas | 503 `CAPACIDAD` | `CERRADA` |
| `CONECTADA` | `LOGIN` bien formado | Consulta LDAP | `VALIDANDO` |
| `CONECTADA` | `REGISTER` | La conexión pasa a ser de nodo (9.2) | fuera de esta máquina |
| `CONECTADA` | Consulta o `EVENT` | 401 `SIN_SESION` | `CONECTADA` |
| `CONECTADA` | Error 400 o 422 | `ERROR`; al quinto seguido cierra | `CONECTADA` o `CERRADA` |
| `CONECTADA` | Vence `T_ident` | 408 `TIEMPO` | `CERRADA` |
| `CONECTADA` | `BYE` | `BYE` | `CERRADA` |
| `VALIDANDO` | LDAP acepta y hay grupo | `LOGIN_OK`, arranca `T_inactividad` | `AUTENTICADA` |
| `VALIDANDO` | 401 `CREDENCIALES` o 403 `ROL`, con `fallos < 3` después de sumar | `fallos + 1`, reinicia `T_ident` | `CONECTADA` |
| `VALIDANDO` | Tercer fallo | `ERROR` y cierre | `CERRADA` |
| `VALIDANDO` | LDAP o DNS no disponibles | 503 | `CONECTADA` |
| `AUTENTICADA` | Consulta permitida | `RESPONSE` + `ITEM`, reinicia `T_inactividad` | `AUTENTICADA` |
| `AUTENTICADA` | Consulta no permitida | 403 `ROL` | `AUTENTICADA` |
| `AUTENTICADA` | `LOGIN` o `REGISTER` | 409 `ESTADO` | `AUTENTICADA` |
| `AUTENTICADA` | `BYE` | `BYE` | `CERRADA` |
| `AUTENTICADA` | Vence `T_inactividad` | 408 `TIEMPO` | `CERRADA` |
| Cualquiera | `recv()` = 0, error de socket o 413 | Libera la conexión | `CERRADA` |

### 9.4 Cliente de administración (`fsm-cliente.mmd`)

| Estado | Evento | Acción | Siguiente |
|---|---|---|---|
| `INICIO` | Abre la aplicación | Muestra el formulario de ingreso | `CREDENCIALES` |
| `CREDENCIALES` | El usuario pulsa "Ingresar" | Guarda las credenciales en memoria | `RESOLVIENDO` |
| `RESOLVIENDO` | `getaddrinfo` responde | | `CONECTANDO` |
| `RESOLVIENDO` | `getaddrinfo` falla | Muestra el error | `ESPERA_REINTENTO` |
| `CONECTANDO` | `connect()` exitoso | Envía `LOGIN`, arranca `T_resp` | `AUTENTICANDO` |
| `CONECTANDO` | `connect()` falla | Muestra el error | `ESPERA_REINTENTO` |
| `AUTENTICANDO` | `LOGIN_OK` | Muestra el perfil, habilita las vistas permitidas | `LISTO` |
| `AUTENTICANDO` | 401 o 403 | Muestra el motivo, borra las credenciales, cierra TCP | `CREDENCIALES` |
| `AUTENTICANDO` | 503, vence `T_resp` o se cae TCP | Muestra el problema | `ESPERA_REINTENTO` |
| `LISTO` | Vence el refresco o el usuario pide una vista | Envía la consulta, arranca `T_resp` | `ESPERANDO_RESPUESTA` |
| `ESPERANDO_RESPUESTA` | `RESPONSE` y todos sus `ITEM` | Actualiza la ventana | `LISTO` |
| `ESPERANDO_RESPUESTA` | `ERROR` 403, 404 o 422 | Muestra el mensaje | `LISTO` |
| `ESPERANDO_RESPUESTA` | Vence `T_resp`, se cae TCP, `ERROR` 408 o 500, o respuesta inválida | Cierra TCP | `ESPERA_REINTENTO` |
| `ESPERA_REINTENTO` | Vence la espera | Duplica la espera hasta 30 s | `RESOLVIENDO` |
| `LISTO` | El usuario cierra la ventana | Envía `BYE` | `FIN` |

## 10. Concurrencia del servidor

Esta sección fija lo que la implementación de la Fase 3 debe respetar para que el protocolo funcione con varios nodos y clientes a la vez.

- Hilo principal: crea los dos sockets con `getaddrinfo` (`AI_PASSIVE`, nodo `NULL`), activa `SO_REUSEADDR` en el socket TCP, hace `bind` y `listen`, lanza los hilos auxiliares y queda en un ciclo de `accept()`.
- Un hilo por conexión TCP aceptada (`pthread_create` + `pthread_detach`), hasta 64 simultáneos. Cada hilo tiene su propio buffer de encuadre y sus propios temporizadores, que revisa usando `SO_RCVTIMEO` de 1 segundo en `recv()`.
- Un hilo receptor UDP que procesa los datagramas uno a uno con `recvfrom()`.
- Un hilo watchdog que despierta cada segundo.
- Un `pthread_mutex_t` protege la tabla de nodos, los historiales y la lista de eventos. Otro protege la escritura del log.
- Orden de candados: si un hilo necesita los dos, toma primero el de la tabla y luego el del log. Nunca al revés. Así no hay interbloqueo.
- Las llamadas a LDAP, a `getaddrinfo` y los `send()` se hacen sin tener tomado el candado de la tabla, porque pueden bloquearse.
- Cada verificación LDAP abre y cierra su propia conexión LDAP dentro del hilo que la necesita; no se comparte un manejador entre hilos.
- El servidor ignora `SIGPIPE` para que escribir en una conexión cerrada devuelva un error en lugar de terminar el proceso.

## 11. Registro de actividad (logging)

El servidor recibe por consola `puerto` y `archivoDeLogs`:

```
./servidor 5050 servidor.log
```

Cada mensaje recibido y cada mensaje enviado se escribe en la salida estándar y en el archivo (abierto en modo de agregar, con `fflush` después de cada línea). Formato de línea:

```
<fecha UTC ISO 8601> <canal> <ip>:<puerto> <dirección> <mensaje>
```

| Parte | Valores |
|---|---|
| canal | `TCP`, `UDP` o `SYS` (eventos internos del servidor) |
| ip:puerto | Dirección de origen de la petición o de destino de la respuesta. En `SYS` se escribe `-` |
| dirección | `<-` recibido, `->` enviado, `--` nota interna (descartes, cambios de estado, fallas de DNS o LDAP) |
| mensaje | La línea sin el `\n`. Los valores de `secret` y `password` se reemplazan por `***`. Los bytes no imprimibles se escriben como `\xNN` |

Ejemplo:

```
2026-10-04T15:02:06Z TCP 192.168.56.21:51522 <- MCD/1.0|REGISTER|req=1|node_id=nodo-01|secret=***|kind=SENSOR|period=5
2026-10-04T15:02:06Z TCP 192.168.56.21:51522 -> MCD/1.0|REGISTER_OK|req=1|node_id=nodo-01|session=4f9c2a7d1e0b8c63|period=5
2026-10-04T15:02:11Z UDP 192.168.56.21:40311 <- MCD/1.0|TELEMETRY|node_id=nodo-01|session=4f9c2a7d1e0b8c63|seq=41|ts=1791126131|cpu=37.5|temp=48.1|bat=91|opstate=OK|uptime=3731
2026-10-04T15:02:17Z SYS - -- nodo-02 estado=SIN_REPORTE anterior=ACTIVO msg_id=srv-3
```

El log no debe contener nunca una contraseña ni un `secret`.

Errores de arranque: si faltan argumentos, el puerto no es un número entre 1 y 65535, no se puede abrir el archivo de log o `bind()` falla (por ejemplo con `EADDRINUSE`), el servidor muestra el motivo y termina con código distinto de 0. Son errores de configuración que impiden prestar el servicio; los fallos de DNS y LDAP no entran en esta categoría y nunca terminan el proceso.

## 12. Resolución de nombres

- Ningún programa contiene direcciones IP. Los nombres vienen de argumentos o de configuración.
- Zona DNS del laboratorio: `monitoreo.lab`, servida por BIND9 en `ns1.monitoreo.lab`. Registros previstos: `ns1`, `servidor` y `ldap`.
- El nodo y el cliente reciben el nombre del servidor (por ejemplo `servidor.monitoreo.lab`) y el puerto. Resuelven con `socket.getaddrinfo` cada vez que van a conectarse, así un cambio de dirección se aplica en la siguiente reconexión.
- El servidor lee el nombre del LDAP de la variable de entorno `MCD_LDAP_HOST` (por defecto `ldap.monitoreo.lab`) y la base de `MCD_LDAP_BASE` (por defecto `dc=monitoreo,dc=lab`). Resuelve el nombre con `getaddrinfo` antes de cada verificación para poder distinguir una falla de DNS (503 `DNS`) de una falla del LDAP (503 `LDAP`).
- Para escuchar, el servidor usa `getaddrinfo` con `AI_PASSIVE` y nodo `NULL`, que equivale a todas las interfaces sin escribir ninguna dirección.
- Un fallo de resolución (`EAI_AGAIN`, `EAI_NONAME` en C; `socket.gaierror` en Python) se registra y se maneja con el backoff de 7.9. Nunca termina el proceso.

## 13. Consideraciones de seguridad

- Las credenciales viajan en texto claro dentro de la red del laboratorio, tanto en MCD/1.0 como en el *bind* LDAP. Es una limitación aceptada para este proyecto. La forma de corregirla sería TLS (MCD sobre TLS y LDAPS), que queda fuera del alcance.
- El `session` de 64 bits aleatorios evita que alguien que no ve el tráfico inyecte telemetría a nombre de un nodo. No protege contra alguien que sí captura el tráfico.
- El conjunto de caracteres seguros impide que `user` o `node_id` alteren el DN o el filtro de búsqueda LDAP, y que un valor rompa una línea del log.
- Los límites de tamaño, de conexiones, de nodos, de intentos de `LOGIN` y de errores seguidos acotan lo que un cliente defectuoso o malicioso puede consumir.
- El límite de un `ERROR` UDP cada 5 segundos por origen evita usar al servidor para reflejar tráfico.
- Ninguna clave real se guarda en el repositorio. Las claves de los nodos se leen de una variable de entorno y las de los usuarios solo existen en el LDAP. Los ejemplos de este documento usan `clave-de-ejemplo`.

## 14. Ejemplos

### 14.1 Sesión de un nodo

```
N->S TCP  MCD/1.0|REGISTER|req=1|node_id=nodo-01|secret=clave-de-ejemplo|kind=SENSOR|period=5
S->N TCP  MCD/1.0|REGISTER_OK|req=1|node_id=nodo-01|session=4f9c2a7d1e0b8c63|period=5
N->S UDP  MCD/1.0|TELEMETRY|node_id=nodo-01|session=4f9c2a7d1e0b8c63|seq=1|ts=1791126131|cpu=37.5|temp=48.1|bat=91|opstate=OK|uptime=3731
N->S UDP  MCD/1.0|TELEMETRY|node_id=nodo-01|session=4f9c2a7d1e0b8c63|seq=2|ts=1791126136|cpu=41.0|temp=49.0|bat=91|opstate=OK|uptime=3736
N->S TCP  MCD/1.0|EVENT|req=2|node_id=nodo-01|msg_id=1791122400-1|ts=1791126138|level=CRITICO|event=UMBRAL_TEMP|value=85.2
S->N TCP  MCD/1.0|ACK|req=2|node_id=nodo-01|msg_id=1791122400-1|dup=0
N->S TCP  MCD/1.0|BYE|req=3
S->N TCP  MCD/1.0|BYE|req=3
```

### 14.2 Sesión de un operador

```
C->S  MCD/1.0|LOGIN|req=1|user=operador1|password=clave-de-ejemplo
S->C  MCD/1.0|LOGIN_OK|req=1|user=operador1|role=operador
C->S  MCD/1.0|HISTORY|req=2|node_id=nodo-01|n=5
S->C  MCD/1.0|RESPONSE|req=2|op=HISTORY|items=2
S->C  MCD/1.0|ITEM|req=2|idx=1|node_id=nodo-01|seq=2|ts=1791126136|cpu=41.0|temp=49.0|bat=91|opstate=OK
S->C  MCD/1.0|ITEM|req=2|idx=2|node_id=nodo-01|seq=1|ts=1791126131|cpu=37.5|temp=48.1|bat=91|opstate=OK
C->S  MCD/1.0|EVENTS|req=3|n=10
S->C  MCD/1.0|ERROR|req=3|code=403|reason=ROL
C->S  MCD/1.0|BYE|req=4
S->C  MCD/1.0|BYE|req=4
```

En este ejemplo el nodo solo había enviado dos muestras, por eso `items=2` aunque se pidieron 5.

### 14.3 Errores frecuentes

Cada par muestra el mensaje recibido por el servidor y su respuesta.

```
C->S  MCD/1.0 LIST req=2
S->C  MCD/1.0|ERROR|req=0|code=400|reason=FORMATO

C->S  MCD/2.0|LIST|req=2
S->C  MCD/1.0|ERROR|req=0|code=400|reason=VERSION

C->S  MCD/1.0|PING|req=2
S->C  MCD/1.0|ERROR|req=0|code=400|reason=TIPO

C->S  MCD/1.0|LIST|req=2                         (antes de LOGIN_OK)
S->C  MCD/1.0|ERROR|req=2|code=401|reason=SIN_SESION

C->S  MCD/1.0|HISTORY|req=5|node_id=nodo-01|n=50
S->C  MCD/1.0|ERROR|req=5|code=422|reason=VALOR|field=n

C->S  MCD/1.0|STATUS|req=6
S->C  MCD/1.0|ERROR|req=6|code=422|reason=FALTA_CAMPO|field=node_id

C->S  MCD/1.0|STATUS|req=7|node_id=nodo-99
S->C  MCD/1.0|ERROR|req=7|code=404|reason=NODO

C->S  (600 bytes sin salto de línea)
S->C  MCD/1.0|ERROR|req=0|code=413|reason=TAMANO   (y cierra la conexión)
```

En los tres primeros casos `req` vale 0 porque el servidor deja de validar antes de leer los campos (sección 6.1).

## 15. Aspectos abiertos

Estos puntos se confirmarán con el profesor o se resolverán durante la implementación. Ninguno cambia el formato de los mensajes.

- Confirmar que usar `libldap` en el servidor es aceptable. Esa biblioteca habla con un servicio estándar; los sockets del protocolo MCD se construyen solo con la API Berkeley. Si no se acepta, la alternativa es validar mediante PAM con `libpam-ldapd`, que consulta el mismo LDAP.
- Persistencia: el estado vive en memoria; si el servidor se reinicia, se pierde el historial y los nodos se vuelven a registrar al recibir 404 por UDP.
- Despliegue en AWS: es opcional en el enunciado. Si se usa, el grupo de seguridad debe abrir el puerto `P` en TCP y en UDP.
