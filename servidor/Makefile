# Servidor MCD/1.0 - objetivos: all (servidor), asan (servidor_asan), clean
CC      ?= gcc
CFLAGS  := -std=gnu11 -Wall -Wextra -pthread -O2 -D_GNU_SOURCE -Iinclude
LDLIBS  := -lldap -llber -pthread
FUENTES := main red protocolo validar manejadores consultas estado auth registro util
OBJ     := $(FUENTES:%=obj/%.o)
SRC     := $(FUENTES:%=src/%.c)

all: servidor

servidor: $(OBJ)
	$(CC) $(CFLAGS) -o $@ $(OBJ) $(LDLIBS)

obj/%.o: src/%.c include/mcd.h | obj
	$(CC) $(CFLAGS) -c -o $@ $<

obj:
	mkdir -p obj

# Binario con ASan y UBSan; UBSan aborta ante el primer problema.
asan: servidor_asan

servidor_asan: $(SRC) include/mcd.h
	$(CC) -std=gnu11 -Wall -Wextra -pthread -D_GNU_SOURCE -Iinclude -g -O1 \
	    -fsanitize=address,undefined -fno-sanitize-recover=undefined \
	    -fno-omit-frame-pointer -o $@ $(SRC) $(LDLIBS)

clean:
	rm -rf obj servidor servidor_asan

.PHONY: all asan clean
