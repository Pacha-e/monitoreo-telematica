# Sistema de monitoreo y control distribuido (MCD/1.0)

Proyecto 1 de ST0255 Telemática (EAFIT, 2026-2) · Emmanuel Hernández.

Varios **nodos** (sensores, equipos de red) reportan su estado a un **servidor central** escrito en C; un
**cliente de administración** consulta ese estado. El servidor valida usuarios y nodos contra un directorio
**LDAP**. Todo habla un protocolo de capa de aplicación propio, **MCD/1.0**, sobre sockets Berkeley:
**UDP** para la telemetría periódica y **TCP** para registro, eventos críticos (con `ACK` e idempotencia por
`msg_id`) y consultas.

```
  nodo-01 (sensor)  ──TCP: REGISTER, EVENT, BYE ──┐
                    ──UDP: TELEMETRY ─────────────┤
  nodo-02 (red)     ──TCP + UDP ──────────────────┼──►  SERVIDOR (C, pthread)  ──bind──►  LDAP
                                                  │         puerto P (TCP y UDP)
  cliente de administración ──TCP: LOGIN, LIST,   │
  (consola)                       STATUS, HISTORY,┘
                                  EVENTS, BYE
```

Los programas no tienen ninguna IP escrita: reciben nombre de host y puerto y resuelven con `getaddrinfo`.

## Estructura

| Ruta | Contenido |
|---|---|
| `servidor/` | Servidor en C: `Makefile`, `src/`, `include/mcd.h` |
| `nodos/` | `nodo_sensor.py` (con batería) y `nodo_red.py` (sin batería) |
| `cliente/` | `cliente_admin.py`: consola interactiva, un solo comando (`--comando`) y `panel` |
| `mcd/` | Biblioteca Python común: protocolo, nodo, cliente, vista y simuladores |
| `infra/ldap/` | LDAP de laboratorio: `slapd.conf.plantilla`, `base.ldif`, README |
| `demo/` | `iniciar_demo.py` y `detener_demo.py` |
| `pruebas/` | Suite automática (`run_all.py`) |
| `docs/` | Especificación del protocolo, propuesta de la Fase 1 y diagramas |

Documentación de la Fase 1: [protocolo MCD/1.0](docs/protocolo/MCD-1.0.md) ·
[propuesta (Entrega 1)](docs/entrega1/Entrega-1.pdf) · [diagramas](docs/diagramas/README.md).

## Requisitos

Linux (probado en Ubuntu 24.04 sobre WSL2): `gcc`, `make`, `python3` (solo biblioteca estándar),
`slapd`, `ldap-utils` y `libldap-dev`.

```sh
sudo apt install build-essential libldap-dev slapd ldap-utils python3
```

## Compilar

```sh
make -C servidor           # genera servidor/servidor
make -C servidor asan      # opcional: servidor_asan (AddressSanitizer + UBSan)
make -C servidor clean
```

## Ejecutar

Desde la raíz del proyecto. Las claves son las ficticias de `infra/ldap/base.ldif`.

**1. LDAP de laboratorio** (usuario normal, puerto 3899)

```sh
D=/tmp/mcd-ldap; mkdir -p $D/db
sed "s|@DIR@|$D|g" infra/ldap/slapd.conf.plantilla > $D/slapd.conf
/usr/sbin/slapadd -f $D/slapd.conf -l infra/ldap/base.ldif        # solo la primera vez
/usr/sbin/slapd -f $D/slapd.conf -h ldap://localhost:3899/ -d 0
```

**2. Servidor**

```sh
MCD_LDAP_HOST=localhost MCD_LDAP_PORT=3899 ./servidor/servidor <puerto> <archivoDeLogs>
# por ejemplo: ... ./servidor/servidor 5050 servidor.log
```

**3. Nodos** (la clave del nodo va en una variable de entorno)

```sh
MCD_NODO_SECRET=clave-nodo-01 python3 nodos/nodo_sensor.py --servidor localhost --puerto 5050 --id nodo-01 --period 2
MCD_NODO_SECRET=clave-nodo-02 python3 nodos/nodo_red.py    --servidor localhost --puerto 5050 --id nodo-02 --period 2
```

**4. Cliente de administración**

```sh
MCD_PASSWORD=clave-admin-lab1 python3 cliente/cliente_admin.py --servidor localhost --puerto 5050 --usuario admin1
mcd> lista
mcd> estado nodo-01
mcd> historial nodo-01 5
mcd> eventos 10            # solo admin; el operador recibe 403
mcd> panel                 # estado de todos los nodos + 5 muestras + eventos, refresco cada 5 s
mcd> salir
```

Un solo comando, sin interacción:

```sh
MCD_PASSWORD=clave-operador-lab1 python3 cliente/cliente_admin.py --servidor localhost --puerto 5050 \
    --usuario operador1 --comando "historial nodo-02 5"
```

Códigos de salida del cliente: 0 bien, 2 credenciales o entrada inválida, 3 ERROR del servidor, 4 red.

| Usuario | Clave | Perfil |
|---|---|---|
| `admin1` | `clave-admin-lab1` | `admin` (todas las consultas, incluida `EVENTS`) |
| `operador1` | `clave-operador-lab1` | `operador` (`LIST`, `STATUS`, `HISTORY`) |
| `sinrol1` | `clave-sinrol-lab1` | autentica pero no tiene perfil (403 `ROL`) |
| `nodo-01` … `nodo-34` | `clave-nodo-01` … `clave-nodo-34` | nodos válidos en LDAP |

## Demostración

```sh
python3 demo/iniciar_demo.py                  # LDAP + servidor + nodo-01 + nodo-02
python3 demo/iniciar_demo.py --abrir-cliente  # además abre el cliente de consola como admin1
python3 demo/detener_demo.py                  # detiene todo (--borrar elimina logs y base LDAP)
```

El estado de la demo queda en `/tmp/mcd-demo`; los logs se ven con `tail -f /tmp/mcd-demo/servidor.log`.

## Pruebas

```sh
python3 pruebas/run_all.py          # compila, levanta un LDAP temporal y corre la suite
python3 pruebas/run_all.py --asan   # además repite la suite con servidor_asan
```

Cada prueba imprime `PASA` o `FALLA`; al final `TOTAL: n pasan, m fallan`, con código de salida 0 si no
falla ninguna.

## Variables de entorno

| Variable | Quién | Defecto | Uso |
|---|---|---|---|
| `MCD_LDAP_HOST`, `MCD_LDAP_PORT`, `MCD_LDAP_BASE` | servidor | `ldap.monitoreo.lab`, `389`, `dc=monitoreo,dc=lab` | ubicación del LDAP |
| `MCD_LDAP_TIMEOUT`, `MCD_T_IDENT`, `MCD_T_INACTIVIDAD` | servidor | `3`, `60`, `300` s | plazos |
| `MCD_NODO_SECRET` | nodos | — | clave del nodo en LDAP |
| `MCD_PASSWORD`, `MCD_USUARIO` | cliente | (pregunta sin eco) | credenciales |
| `MCD_SERVIDOR`, `MCD_PUERTO` | nodos y cliente | — | alternativa a `--servidor` / `--puerto` |
| `MCD_DEMO_DIR`, `MCD_TMP` | demo, pruebas | `/tmp/...` | directorio de trabajo |

## Autor

Emmanuel Hernández
