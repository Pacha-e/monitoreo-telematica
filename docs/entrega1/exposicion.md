# Exposición de la Fase 1

ST0255 Telemática, 2026-2. Emmanuel Hernández. 4 de octubre de 2026.

Duración objetivo: 4 minutos 40 segundos, para dejar margen dentro de los 5 minutos.

## Diapositivas

### Diapositiva 1. Problema y arquitectura

- Título: Sistema de monitoreo distribuido con MCD/1.0.
- Diagrama de despliegue simplificado: `nodo-01` y `nodo-02` a la izquierda, servidor en C al centro, cliente Tkinter a la derecha, BIND9 y OpenLDAP abajo.
- Una línea: "Dos tipos de información con necesidades opuestas: telemetría periódica y eventos críticos."

### Diapositiva 2. Transporte por tipo de mensaje

Tabla reducida:

| Flujo | Transporte | Razón principal |
|---|---|---|
| Registro | TCP | Crea estado, no se puede perder |
| Telemetría cada 5 s | UDP | La siguiente muestra reemplaza a la perdida |
| Eventos | TCP + `ACK` | No se pueden perder ni duplicar |
| Login y consultas | TCP | Sesión, orden y respuestas largas |

### Diapositiva 3. Formato del protocolo

- `MCD/1.0|TIPO|clave=valor|...\n`, máximo 512 bytes.
- Un ejemplo de `TELEMETRY` y uno de `EVENT` con su `ACK`.
- Los 15 tipos agrupados por las 7 operaciones que pide el enunciado.

### Diapositiva 4. Reglas y máquinas de estado

- Máquina del nodo visto por el servidor: `DESCONOCIDO`, `ACTIVO`, `SIN_REPORTE`, `DESCONECTADO`.
- Tres reglas: nada antes de registrarse o autenticarse; `seq` para pérdida, duplicado y desorden; `msg_id` para no duplicar eventos.

### Diapositiva 5. Errores, servicios externos y siguientes pasos

- Códigos 400, 401, 403, 404, 408, 409, 413, 422, 500, 503.
- DNS y LDAP caídos: log y reintento con espera creciente, el proceso no termina.
- Un hilo por conexión TCP, un hilo UDP y un watchdog.
- Fase 2: servidor con sockets y parser; Fase 3: concurrencia y pruebas de error.

## Guion

### 0:00 a 0:40. Diapositiva 1

"El sistema tiene dos nodos que reportan su estado, un servidor central en C y un cliente de administración en Python. Los nodos y el cliente nunca hablan entre sí; todo pasa por el servidor. Además el sistema usa dos servicios reales: un DNS con BIND9, porque el código no puede tener direcciones IP, y un directorio OpenLDAP para autenticar usuarios y nodos. Lo que más condicionó el diseño es que el enunciado describe dos tipos de información con necesidades opuestas: la telemetría, que se puede perder de vez en cuando, y los eventos críticos, que no."

### 0:40 a 1:50. Diapositiva 2

"Por eso no elegí un solo transporte. La telemetría va por UDP: es pequeña, unos 130 bytes, sale cada 5 segundos y si se pierde una, la siguiente la reemplaza. Con TCP, una muestra perdida se retransmitiría y detendría a las siguientes detrás de ella, y lo que quiero es el dato más reciente. Lo demás va por TCP. El registro crea una sesión, los eventos no se pueden perder y las consultas necesitan orden y una sesión autenticada. Para los eventos agregué una confirmación de aplicación, porque TCP garantiza que los bytes llegan mientras la conexión exista, pero no me dice si el servidor alcanzó a guardar el evento antes de que la conexión se cayera."

### 1:50 a 2:50. Diapositiva 3

"El protocolo es de texto, una línea por mensaje: versión, tipo y campos clave igual a valor separados por barras, con un máximo de 512 bytes. Lo hice de texto para poder probar el servidor con netcat y leer todo en Wireshark. El salto de línea es lo que me permite separar mensajes en TCP, que entrega un flujo de bytes y no mensajes. Los valores solo admiten letras, dígitos y unos pocos signos, así ningún valor puede romper el formato ni meterse en una consulta LDAP. Hay quince tipos de mensaje que cubren las siete operaciones que pide el enunciado."

### 2:50 a 3:50. Diapositiva 4

"Tres reglas sostienen el protocolo. Primero, nada funciona antes de registrarse o autenticarse. Segundo, cada telemetría lleva un número de secuencia: si se repite la descarto como duplicada, si es menor la descarto como atrasada y si salta, cuento las perdidas. Tercero, cada evento lleva un identificador que combina la hora de arranque del nodo y un contador; si el nodo lo reenvía después de reconectarse, el servidor lo reconoce y confirma sin guardarlo dos veces. Esta máquina es la del nodo visto desde el servidor: si pasan tres periodos sin telemetría, el nodo pasa a sin reporte, y vuelve a activo con la siguiente muestra."

### 3:50 a 4:40. Diapositiva 5

"Los errores tienen códigos parecidos a los de HTTP, con un motivo enumerado, y un orden de validación fijo para que la respuesta sea predecible. Si el DNS o el LDAP fallan, el servidor responde 503, lo registra y reintenta con una espera creciente; ningún proceso termina por eso. Para la concurrencia uso un hilo por conexión TCP, un hilo para UDP y un watchdog, con un mutex para la tabla y otro para el log. En la Fase 2 implemento los sockets, el parser y los mensajes básicos; en la Fase 3, la concurrencia y las pruebas de cada error. Gracias."

## Banco de preguntas difíciles

1. ¿Por qué la telemetría va por UDP si se puede perder?
   Porque el enunciado dice que perder alguna es tolerable si el dato se actualiza. Con TCP una muestra perdida se retransmite y bloquea a las siguientes mientras tanto; prefiero el dato nuevo. La pérdida no queda oculta: el `seq` me permite contarla.

2. ¿Por qué no mandar los eventos por UDP con confirmación?
   Necesitaría confirmación, temporizador, retransmisión, detección de duplicados y orden. Eso es casi rehacer TCP, y el enunciado pide no hacerlo. Los eventos son esporádicos y ya hay una conexión TCP abierta por el registro.

3. Si TCP ya es confiable, ¿para qué el `ACK` de los eventos?
   TCP confirma que los bytes llegaron al sistema operativo del servidor, no que la aplicación guardó el evento. Si la conexión se cae justo después de enviar, el nodo no sabe qué pasó. El `ACK` se envía después de guardar, y el `msg_id` evita duplicar si el nodo reenvía.

4. ¿Cómo separan los mensajes en TCP?
   TCP es un flujo de bytes: un `recv()` puede traer medio mensaje o varios. Guardo lo recibido en un buffer por conexión y saco un mensaje cada vez que encuentro un `\n`. Si se acumulan 512 bytes sin `\n`, respondo 413 y cierro.

5. ¿Qué pasa si llega un mensaje de 600 bytes?
   Por TCP, 413 y cierre de esa conexión, porque ya no puedo saber dónde empieza el siguiente mensaje. Por UDP, descarto el datagrama y lo registro, sin responder.

6. ¿El contador de pérdidas es exacto?
   No, es un estimado por exceso. Si `seq=44` llega después de `seq=45`, ya lo había contado como perdido y además cuenta como atrasado. Para ver si la red está perdiendo datos es suficiente, y lo dejé documentado.

7. ¿Qué pasa con el `msg_id` si el nodo se reinicia?
   El `msg_id` es `<arranque>-<contador>`. El arranque es la hora en que inició el proceso, así que después de un reinicio los identificadores son distintos aunque el contador vuelva a 1. Solo fallaría si el reloj del nodo retrocede.

8. ¿Cómo pueden usar el mismo puerto para TCP y UDP?
   Son espacios de puertos independientes. Un socket se identifica por protocolo, IP y puerto de cada extremo, así que el 5050 TCP y el 5050 UDP son sockets distintos. Así cumplo el único parámetro de puerto que pide el enunciado.

9. ¿Qué pasa si el DNS falla? ¿Cómo escucha el servidor sin escribir una IP?
   `getaddrinfo` devuelve un error, se registra y se reintenta con espera de 1, 2, 4 hasta 30 segundos, sin terminar el proceso. Para escuchar uso `getaddrinfo` con `AI_PASSIVE` y sin nombre, que equivale a todas las interfaces.

10. ¿Usar `libldap` no viola la regla de usar solo la API de Berkeley?
    La regla es para construir los sockets del protocolo, y esos son Berkeley. `libldap` es el cliente de otro servicio estándar, igual que la resolución de nombres usa el resolvedor del sistema. De todas formas lo voy a confirmar con el profesor; la alternativa es PAM con `libpam-ldapd`.

11. ¿Por qué hilos y no `fork()` ni `select()`?
    Con `fork()` cada proceso tendría su copia de la tabla de nodos y el hilo UDP no podría actualizar lo que leen los demás sin memoria compartida. Con `select()` una verificación LDAP lenta bloquearía a todos. Las conexiones esperadas son pocas, así que un hilo por conexión es razonable.

12. Si dos clientes piden el historial mientras llega telemetría, ¿cómo evitan condiciones de carrera?
    Un mutex protege la tabla. Quien responde una consulta copia los datos con el mutex tomado, lo suelta y después envía. El log tiene su propio mutex y siempre se toman en el mismo orden, tabla y luego log, para que no haya interbloqueo.

13. Las claves viajan en texto claro. ¿No es un problema?
    Sí, es una limitación que acepto para una red de laboratorio y que está declarada. La solución sería TLS para MCD y LDAPS. Lo que sí hago es no escribir claves en el log, no guardarlas en el repositorio y restringir los caracteres para que no se puedan inyectar en LDAP.

14. ¿Cuándo pasa un nodo a `SIN_REPORTE` y por qué tres periodos?
    Cuando lleva más de tres periodos sin telemetría válida, medido con el reloj del servidor. Una sola pérdida en UDP es normal y no debería generar una alarma; tres seguidas ya indican un problema del nodo o de la red.

15. ¿Cómo detecta el servidor que un cliente o un nodo se desconectó?
    Si `recv()` devuelve 0, el otro extremo cerró; si devuelve -1 con un error que no es un vencimiento de tiempo, la conexión falló. En los dos casos libero la conexión y, si era un nodo, lo marco `DESCONECTADO`. Para conexiones que mueren sin aviso, el nodo deja de enviar telemetría y el watchdog lo marca `SIN_REPORTE`; además el servidor activa `SO_KEEPALIVE`.
