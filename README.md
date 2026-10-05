# Sistema de monitoreo distribuido

Proyecto de la materia ST0255 Telemática, 2026-2.

La idea es construir un sistema donde varios nodos reportan su estado a un servidor central. Un cliente de administración consulta el estado actual, el historial y los eventos detectados. El proyecto usa un protocolo de aplicación propio sobre sockets Berkeley.

## Estado

- [x] Investigación del material del curso
- [x] Fase 1: diseño y arquitectura
- [ ] Fase 2: comunicación básica
- [ ] Fase 3: concurrencia, robustez y pruebas

## Entrega 1

- [Propuesta en PDF](docs/entrega1/Entrega-1.pdf)
- [Propuesta editable](docs/entrega1/propuesta.md)
- [Especificación del protocolo MCD/1.0](docs/protocolo/MCD-1.0.md)
- [Diagramas y exportaciones](docs/diagramas/README.md)
- [Matriz de trazabilidad](docs/entrega1/trazabilidad.md)
- [Guion de exposición](docs/entrega1/exposicion.md)

Validación local de los ejemplos del protocolo:

```bash
python3 tools/validar_ejemplos.py
```

## Autor

Emmanuel Hernández
