# Anexo A. Diagramas

Los diagramas están generados con Mermaid; las fuentes editables están en `docs/diagramas/` del repositorio https://github.com/Pacha-e/monitoreo-telematica, junto con sus exportaciones en `svg/` y `png/`. Las tablas de transición de la especificación (sección 9 de `docs/protocolo/MCD-1.0.md`) son la referencia normativa; los diagramas largos se dividen en partes para que cada una sea legible a tamaño de página.

## Arquitectura de despliegue

![Arquitectura de despliegue](../diagramas/svg/despliegue.svg)

## Máquina de estados del nodo

Parte 1: arranque y resolución.

![Máquina de estados del nodo, parte 1](../diagramas/svg/fsm-nodo-1.svg)

Parte 2: registro.

![Máquina de estados del nodo, parte 2](../diagramas/svg/fsm-nodo-2.svg)

Parte 3: operación, eventos y cierre.

![Máquina de estados del nodo, parte 3](../diagramas/svg/fsm-nodo-3.svg)

## Estado del nodo visto por el servidor

Parte 1: registro y vigilancia.

![Estado del nodo visto por el servidor, parte 1](../diagramas/svg/fsm-servidor-nodo-1.svg)

Parte 2: desconexión y reenganche.

![Estado del nodo visto por el servidor, parte 2](../diagramas/svg/fsm-servidor-nodo-2.svg)

## Sesión administrativa en el servidor

Parte 1: identificación y autenticación.

![Sesión administrativa, parte 1](../diagramas/svg/fsm-sesion-admin-1.svg)

Parte 2: sesión autenticada y cierre.

![Sesión administrativa, parte 2](../diagramas/svg/fsm-sesion-admin-2.svg)

## Máquina de estados del cliente administrativo

Parte 1: inicio y conexión.

![Máquina de estados del cliente, parte 1](../diagramas/svg/fsm-cliente-1.svg)

Parte 2: autenticación.

![Máquina de estados del cliente, parte 2](../diagramas/svg/fsm-cliente-2.svg)

Parte 3: consultas y cierre.

![Máquina de estados del cliente, parte 3](../diagramas/svg/fsm-cliente-3.svg)

## Secuencia de registro

Caso exitoso.

![Registro exitoso](../diagramas/svg/secuencia-registro-1.svg)

Caso con credenciales inválidas.

![Registro con credenciales inválidas](../diagramas/svg/secuencia-registro-2.svg)

## Secuencia de telemetría

Parte 1: recepción, pérdida, retraso y duplicado.

![Telemetría, parte 1](../diagramas/svg/secuencia-telemetria-1.svg)

Parte 2: vigilancia del watchdog y recuperación.

![Telemetría, parte 2](../diagramas/svg/secuencia-telemetria-2.svg)

## Secuencia de evento crítico

Parte 1: evento con confirmación inmediata.

![Evento crítico, parte 1](../diagramas/svg/secuencia-evento-1.svg)

Parte 2: confirmación perdida y reenvío sin duplicados.

![Evento crítico, parte 2](../diagramas/svg/secuencia-evento-2.svg)

## Secuencia de autenticación y consultas

Parte 1: autenticación con LDAP y consulta LIST.

![Autenticación y consultas, parte 1](../diagramas/svg/secuencia-consulta-1.svg)

Parte 2: historial, permisos y cierre.

![Autenticación y consultas, parte 2](../diagramas/svg/secuencia-consulta-2.svg)

## Errores del protocolo

Parte 1: errores que mantienen la conexión abierta.

![Errores del protocolo, parte 1](../diagramas/svg/secuencia-errores-1.svg)

Parte 2: transporte equivocado, tamaño excedido y tiempo de identificación.

![Errores del protocolo, parte 2](../diagramas/svg/secuencia-errores-2.svg)

## Comportamiento ante servicios caídos

Caso 1: DNS sin respuesta al arrancar un nodo.

![Servicios caídos, caso 1](../diagramas/svg/secuencia-servicios-caidos-1.svg)

Caso 2: LDAP caído durante un LOGIN.

![Servicios caídos, caso 2](../diagramas/svg/secuencia-servicios-caidos-2.svg)

Caso 2 (continuación): recuperación del LDAP.

![Servicios caídos, caso 2 continuación](../diagramas/svg/secuencia-servicios-caidos-3.svg)

Caso 3: DNS no resuelve el nombre del LDAP.

![Servicios caídos, caso 3](../diagramas/svg/secuencia-servicios-caidos-4.svg)
