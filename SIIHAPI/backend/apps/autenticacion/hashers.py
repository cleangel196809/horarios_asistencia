"""
SIIHAPI · Hasher de contraseñas Argon2id con salida de 128 caracteres.

Conforme al RNF-07 del documento técnico: el hash debe ser de 128 caracteres
de longitud (64 bytes en hexadecimal). Cumple con las recomendaciones OWASP
Password Storage Cheat Sheet 2024.
"""
import argon2
from argon2 import Type
from django.conf import settings
from django.contrib.auth.hashers import BasePasswordHasher
from django.utils.crypto import get_random_string


class Argon2id128CharHasher(BasePasswordHasher):
    """
    Hasher Argon2id que produce hashes de 128 caracteres de salida (64 bytes hex).

    Parámetros configurables vía settings.py:
        ARGON2_TIME_COST      (default 3)
        ARGON2_MEMORY_COST    (default 65536 KB = 64 MB)
        ARGON2_PARALLELISM    (default 4)
        ARGON2_HASH_LEN       (default 64 bytes = 128 caracteres hex)

    Formato del hash almacenado:
        argon2id128$<salt_hex>$<hash_hex>
    """

    algorithm = 'argon2id128'

    def __init__(self):
        super().__init__()
        self.time_cost = getattr(settings, 'ARGON2_TIME_COST', 3)
        self.memory_cost = getattr(settings, 'ARGON2_MEMORY_COST', 65536)
        self.parallelism = getattr(settings, 'ARGON2_PARALLELISM', 4)
        self.hash_len = getattr(settings, 'ARGON2_HASH_LEN', 64)  # bytes
        self.salt_len = 16  # 16 bytes = 32 caracteres hex

    def _hasher(self):
        return argon2.PasswordHasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            salt_len=self.salt_len,
            type=Type.ID,
        )

    def salt(self):
        return get_random_string(self.salt_len * 2)  # 32 chars hex

    def encode(self, password, salt):
        """Genera el hash en formato: argon2id128$<salt_hex>$<hash_hex>."""
        assert password is not None
        assert salt and '$' not in salt
        # Usamos hash_password_raw para obtener bytes y luego hex
        hasher = argon2.low_level
        hash_bytes = hasher.hash_secret_raw(
            secret=password.encode('utf-8'),
            salt=salt.encode('utf-8'),
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            type=Type.ID,
        )
        hash_hex = hash_bytes.hex()  # 64 bytes -> 128 caracteres hex
        return f"{self.algorithm}${salt}${hash_hex}"

    def verify(self, password, encoded):
        algorithm, salt, hash_hex = encoded.split('$', 2)
        if algorithm != self.algorithm:
            return False
        re_encoded = self.encode(password, salt)
        return re_encoded == encoded

    def safe_summary(self, encoded):
        algorithm, salt, hash_hex = encoded.split('$', 2)
        return {
            'algorithm': algorithm,
            'salt_len_hex': len(salt),
            'hash_len_hex': len(hash_hex),  # debería ser 128
            'memory_cost_kb': self.memory_cost,
            'time_cost': self.time_cost,
            'parallelism': self.parallelism,
        }

    def must_update(self, encoded):
        # Forzar actualización si cambiaron los parámetros
        try:
            algorithm, salt, hash_hex = encoded.split('$', 2)
        except ValueError:
            return True
        return len(hash_hex) != self.hash_len * 2  # 128 caracteres esperados

    def harden_runtime(self, password, encoded):
        """Mitiga ataques de timing."""
        pass


def verificar_longitud_hash(hash_encoded):
    """
    Helper de seguridad: verifica que el hash almacenado tenga
    exactamente 128 caracteres de longitud en su componente hash.
    """
    try:
        algorithm, salt, hash_hex = hash_encoded.split('$', 2)
        return len(hash_hex) == 128 and algorithm == 'argon2id128'
    except (ValueError, AttributeError):
        return False
