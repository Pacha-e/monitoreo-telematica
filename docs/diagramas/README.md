# Diagramas

Fuentes Mermaid de los diagramas de la Fase 1. Cada fuente fue validada con Mermaid CLI 12.0.0. Las exportaciones listas para incluir en la entrega están en `svg/` y `png/`; las fuentes `.mmd` son la versión editable.

Las tablas de transiciones de la especificación son la referencia normativa. Si un diagrama y una tabla no coinciden, manda la tabla y el diagrama se corrige.

| Archivo | Tipo | Qué muestra | Propuesta | Especificación |
|---|---|---|---|---|
| `despliegue.mmd` | Despliegue | Máquinas lógicas, puertos, nombres DNS y qué transporte usa cada flujo | §4 Arquitectura propuesta | §2.2, §2.3 |
| `fsm-nodo.mmd` | Máquina de estados | Ciclo de vida del nodo: resolución, conexión, registro, operación, espera de `ACK`, reintento y cierre | §9.1 | §9.1 |
| `fsm-servidor-nodo.mmd` | Máquina de estados | Estado de cada nodo en la tabla del servidor: `DESCONOCIDO`, `ACTIVO`, `SIN_REPORTE`, `DESCONECTADO` | §9.2 | §9.2, §7.8 |
| `fsm-sesion-admin.mmd` | Máquina de estados | Conexión de un cliente de administración en el servidor: identificación, validación LDAP, sesión autenticada y cierre | §9.3 | §9.3, §7.5 |
| `fsm-cliente.mmd` | Máquina de estados | Cliente Tkinter: credenciales, conexión, autenticación, consultas periódicas y reconexión | §9.4 | §9.4 |
| `secuencia-registro.mmd` | Secuencia | DNS, conexión TCP, `REGISTER`, verificación en LDAP y `REGISTER_OK` o 401 | §6.2 flujo 1 | §7.2 |
| `secuencia-telemetria.mmd` | Secuencia | Telemetría UDP con un datagrama perdido, uno atrasado y uno duplicado; paso a `SIN_REPORTE` y recuperación | §6.2 flujo 2; §10.2 | §7.3, §7.8 |
| `secuencia-evento.mmd` | Secuencia | `EVENT` con `ACK`, caída de la conexión antes del `ACK`, reenvío y deduplicación con `dup=1` | §6.2 flujo 3; §10.3 | §7.4 |
| `secuencia-consulta.mmd` | Secuencia | `LOGIN` con LDAP, `LIST` periódico, `HISTORY` de 5 muestras, `EVENTS` rechazado al operador y `BYE` | §6.2 flujo 4; §12 | §7.5, §7.6 |
| `secuencia-errores.mmd` | Secuencia | Respuestas 401, 400, 422, 404, 409, 413 y 408 | §11 | §6, §6.1 |
| `secuencia-servicios-caidos.mmd` | Secuencia | DNS sin respuesta en el nodo, LDAP caído durante un `LOGIN` y DNS que no resuelve el LDAP en el servidor | §11, §13 | §7.9, §12 |

## Convenciones

- Los mensajes MCD aparecen completos cuando importa ver sus campos y abreviados (por ejemplo `TELEMETRY seq=43`) cuando solo importa la secuencia.
- `P` es el puerto que recibe el servidor por consola.
- Las claves de ejemplo son `clave-de-ejemplo`; ninguna clave real aparece en los diagramas.
