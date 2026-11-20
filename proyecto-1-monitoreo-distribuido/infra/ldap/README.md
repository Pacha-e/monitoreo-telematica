# LDAP de laboratorio

Directorio OpenLDAP minimo para probar el servidor MCD/1.0 sin servicios del
sistema ni `root`. Todas las claves son **ficticias** y viven solo en
`base.ldif`.

## Archivos

| Archivo | Para que sirve |
|---|---|
| `slapd.conf.plantilla` | Configuracion de `slapd` (backend `mdb`, esquemas `core`, `cosine`, `inetorgperson`). `@DIR@` se reemplaza por el directorio de trabajo |
| `base.ldif` | Arbol `dc=monitoreo,dc=lab`: `ou=people`, `ou=groups`, `ou=devices`, 3 usuarios, 2 grupos y 34 nodos |

## Contenido de `base.ldif`

| Entrada | Clave de laboratorio | Nota |
|---|---|---|
| `uid=admin1,ou=people` | `clave-admin-lab1` | miembro de `cn=admins` -> perfil `admin` |
| `uid=operador1,ou=people` | `clave-operador-lab1` | miembro de `cn=operadores` -> perfil `operador` |
| `uid=sinrol1,ou=people` | `clave-sinrol-lab1` | autentica pero no esta en ningun grupo -> 403 `ROL` |
| `cn=nodo-01` a `cn=nodo-34`, `ou=devices` | `clave-nodo-01` a `clave-nodo-34` | `device` + `simpleSecurityObject` |

Los grupos son `groupOfNames` con atributo `member`, como pide la seccion 7.5
de la norma. Los nodos son 34 para poder probar el limite de 32 nodos.

## Levantarlo a mano

Como usuario normal, en un directorio propio y un puerto alto (aqui 3899):

```sh
D=$PWD/ldap-lab; mkdir -p "$D/db"
sed "s|@DIR@|$D|g" slapd.conf.plantilla > "$D/slapd.conf"
/usr/sbin/slapadd -f "$D/slapd.conf" -l base.ldif       # solo la primera vez
/usr/sbin/slapd -f "$D/slapd.conf" -h ldap://localhost:3899/ -d 0 &
```

`slapd` queda en primer plano con `-d 0` y escribe su pid en `$D/slapd.pid`.
Para detenerlo: `kill "$(cat "$D/slapd.pid")"`.

Comprobar un login y el perfil:

```sh
ldapsearch -x -H ldap://localhost:3899/ \
  -D uid=admin1,ou=people,dc=monitoreo,dc=lab -w clave-admin-lab1 \
  -b ou=groups,dc=monitoreo,dc=lab "(member=uid=admin1,ou=people,dc=monitoreo,dc=lab)" cn
```

Arrancar el servidor contra ese LDAP:

```sh
MCD_LDAP_HOST=localhost MCD_LDAP_PORT=3899 ./servidor 5050 servidor.log
```

## Lo que hace la suite de pruebas

`pruebas/mcdlib.py` (clase `LdapLab`) ejecuta exactamente este procedimiento en
un directorio temporal bajo `pruebas/.tmp/`, con un puerto libre elegido en
tiempo de ejecucion, y lo detiene al terminar. Para la prueba de "LDAP caido"
detiene `slapd` y lo vuelve a arrancar sobre la misma base.

## Demo

`demo/iniciar_demo.py` y `demo/detener_demo.py` levantan y detienen este mismo LDAP junto
con el servidor y los nodos.
