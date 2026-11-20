import unittest

from validar_ejemplos import limpiar_ejemplo, validar_linea


class ValidarLineaTest(unittest.TestCase):
    def test_acepta_mensaje_valido(self):
        mensaje = "MCD/1.0|LIST|req=1\n"
        self.assertEqual(validar_linea(mensaje), [])

    def test_rechaza_mensaje_demasiado_largo(self):
        mensaje = "MCD/1.0|EVENT|req=1|value=" + "a" * 500 + "\n"
        self.assertIn("supera 512 bytes", validar_linea(mensaje))

    def test_rechaza_claves_repetidas(self):
        mensaje = "MCD/1.0|LIST|req=1|req=2\n"
        self.assertIn("clave repetida: req", validar_linea(mensaje))

    def test_limpia_anotacion_fuera_del_mensaje(self):
        linea = "MCD/1.0|LIST|req=2   (antes de LOGIN_OK)"
        self.assertEqual(limpiar_ejemplo(linea), "MCD/1.0|LIST|req=2\n")


if __name__ == "__main__":
    unittest.main()
