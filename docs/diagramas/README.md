# Diagramas

Fuentes Mermaid de los diagramas de la Fase 1. Cada fuente fue validada con Mermaid CLI 12.0.0. Las exportaciones listas para incluir en la entrega están en `svg/` y `png/`; las fuentes `.mmd` son la versión editable.

Las tablas de transiciones de la especificación son la referencia normativa. Si un diagrama y una tabla no coinciden, manda la tabla y el diagrama se corrige.

Los diagramas largos se dividen en partes numeradas (`-1`, `-2`, `-3`) para que el texto sea legible al tamaño de página de la entrega. Cada parte es una fuente independiente y completa por sí misma; la continuación se indica en el título de la parte.

| Archivo | Tipo | Qué muestra | Propuesta | Especificación |
|---|---|---|---|---|
| `despliegue.mmd` | Despliegue | Máquinas lógicas, puertos, nombres DNS y qué transporte usa cada flujo | §4 Arquitectura propuesta | §2.2, §2.3 |
| `fsm-nodo-1.mmd`, `-2`, `-3` | Máquina de estados | Ciclo de vida del nodo: arranque y resolución; registro; operación, espera de `ACK`, reintento y cierre | §9.1 | §9.1 |
| `fsm-servidor-nodo-1.mmd`, `-2` | Máquina de estados | Estado de cada nodo en la tabla del servidor: `DESCONOCIDO`, `ACTIVO`, `SIN_REPORTE`, `DESCONECTADO` | §9.2 | §9.2, §7.8 |
| `fsm-sesion-admin-1.mmd`, `-2` | Máquina de estados | Conexión de un cliente de administración en el servidor: identificación, validación LDAP, sesión autenticada y cierre | §9.3 | §9.3, §7.5 |
| `fsm-cliente-1.mmd`, `-2`, `-3` | Máquina de estados | Cliente Tkinter: inicio y conexión; autenticación; consultas periódicas y reconexión | §9.4 | §9.4 |
| `secuencia-registro-1.mmd`, `-2` | Secuencia | DNS, conexión TCP, `REGISTER` y verificación en LDAP: caso exitoso y caso con credenciales inválidas | §6.2 flujo 1 | §7.2 |
| `secuencia-telemetria-1.mmd`, `-2` | Secuencia | Telemetría UDP con un datagrama perdido, uno atrasado y uno duplicado; luego el watchdog y la recuperación | §6.2 flujo 2; §10.2 | §7.3, §7.8 |
| `secuencia-evento-1.mmd`, `-2` | Secuencia | `EVENT` con `ACK`; luego confirmación perdida, reenvío y deduplicación con `dup=1` | §6.2 flujo 3; §10.3 | §7.4 |
| `secuencia-consulta-1.mmd`, `-2` | Secuencia | `LOGIN` con LDAP y `LIST` periódico; luego `HISTORY`, `EVENTS` rechazado al operador y `BYE` | §6.2 flujo 4; §12 | §7.5, §7.6 |
| `secuencia-errores-1.mmd`, `-2` | Secuencia | Errores que mantienen la conexión abierta (401, 400, 422, 404, 409); luego 409 `TRANSPORTE`, 413 y 408 | §11 | §6, §6.1 |
| `secuencia-servicios-caidos-1.mmd` a `-4` | Secuencia | DNS sin respuesta en el nodo; LDAP caído y su recuperación; DNS que no resuelve el LDAP | §11, §13 | §7.9, §12 |

## Convenciones

- Los mensajes MCD aparecen completos cuando importa ver sus campos y abreviados (por ejemplo `TELEMETRY seq=43`) cuando solo importa la secuencia.
- `P` es el puerto que recibe el servidor por consola.
- Las claves de ejemplo son `clave-de-ejemplo`; ninguna clave real aparece en los diagramas.
