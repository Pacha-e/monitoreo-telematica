# Proyecto 2 — Interconexión de sistemas autónomos y acceso a servicios

ST0255 Telemática · Universidad EAFIT · Emmanuel Hernández (trabajo individual)

Red montada en Cisco Packet Tracer 9.0.1: un cliente (AS1) que recibe sus direcciones
por DHCP y accede por IP y por nombre a los servidores DNS y WEB de un proveedor (AS99).

## Contenido

| Archivo o carpeta | Qué es |
|---|---|
| `Entrega2-EmmanuelHernandez.pkt` | Red en Packet Tracer |
| `Informe-Entrega2-EmmanuelHernandez.pdf` | Informe con decisiones, justificación y evidencias |
| `configs/` | Configuración de cada router y del switch |
| `evidencias/` | Capturas de las pruebas en el simulador |

## Resumen del diseño

| Parte | Solución |
|---|---|
| AS1 (cliente) | R1, R2, R3, R4 con RIP versión 2; rutas estáticas por defecto hacia R4 |
| AS99 (proveedor) | R5, R6, R7 con OSPF, área 0 |
| Interconexión | eBGP entre R4 (AS 1) y R6 (AS 99); NAT con sobrecarga en R4 |
| Redes del cliente | 10.0.0.0/24 (VLAN 10 en SW1) y 172.16.0.0/24 |
| DHCP | Servidor en 192.168.100.2, con `ip helper-address` en R1 y R3 |
| DNS | 200.99.5.2, registro `www.as99.com` → 200.99.7.2 |
| WEB | 200.99.7.2 |

## Cómo probar

1. Abrir el `.pkt` en Packet Tracer y esperar a que los enlaces queden en verde.
2. En PC0: Desktop → Command Prompt → `ping 200.99.7.2` y `nslookup www.as99.com`.
3. En PC0: Desktop → Web Browser → `http://www.as99.com`.
