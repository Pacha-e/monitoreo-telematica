# Anexo A. Diagramas

Los diagramas siguientes resumen la arquitectura, los estados y los intercambios principales. Las tablas de transición de `docs/protocolo/MCD-1.0.md` son la referencia normativa.

## Despliegue

![Arquitectura de despliegue](../diagramas/svg/despliegue.svg)

## Máquinas de estado

![Máquina de estados del nodo](../diagramas/svg/fsm-nodo.svg)

![Estado del nodo visto por el servidor](../diagramas/svg/fsm-servidor-nodo.svg)

![Sesión administrativa en el servidor](../diagramas/svg/fsm-sesion-admin.svg)

![Máquina de estados del cliente administrativo](../diagramas/svg/fsm-cliente.svg)

## Secuencias principales

![Registro de un nodo](../diagramas/svg/secuencia-registro.svg)

![Telemetría periódica](../diagramas/svg/secuencia-telemetria.svg)

![Evento crítico y confirmación](../diagramas/svg/secuencia-evento.svg)

![Autenticación y consultas](../diagramas/svg/secuencia-consulta.svg)

## Manejo de fallos

![Errores del protocolo](../diagramas/svg/secuencia-errores.svg)

![Comportamiento ante servicios caídos](../diagramas/svg/secuencia-servicios-caidos.svg)
