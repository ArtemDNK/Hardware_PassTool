# Зашифрованное хранилище паролей.
# Формат vault.bin:
#   MAGIC(4) | iterations(4, BE) | salt(16) | iv(16) | ciphertext(N*16) | HMAC-SHA256(32)
# Ключ: PBKDF2-HMAC-SHA256(PIN, salt) -> enc_key (AES-256-CBC) и mac_key (HMAC).
# Схема encrypt-then-MAC: неверный PIN или подмена файла ловятся проверкой HMAC.
import os
import json

try:
    import hashlib
except ImportError:  # на платах без нативного hashlib (очень медленно)
    import adafruit_hashlib as hashlib
import aesio

VAULT = "/vault.bin"
TMP = "/vault.tmp"
ATTEMPTS = "/attempts.txt"
IMPORT = "/import.txt"
MAGIC = b"DPV1"


def _sha(data):
    h = hashlib.sha256()
    h.update(data)
    return h.digest()


def _pads(key):
    if len(key) > 64:
        key = _sha(key)
    key = key + bytes(64 - len(key))
    return bytes(b ^ 0x36 for b in key), bytes(b ^ 0x5C for b in key)


def hmac_sha256(key, msg):
    ik, ok = _pads(key)
    return _sha(ok + _sha(ik + msg))


def pbkdf2_sha256(password, salt, iterations):
    """PBKDF2-HMAC-SHA256, один блок (32 байта)."""
    ik, ok = _pads(password)
    u = _sha(ok + _sha(ik + salt + b"\x00\x00\x00\x01"))
    acc = int.from_bytes(u, "big")
    for _ in range(iterations - 1):
        u = _sha(ok + _sha(ik + u))
        acc ^= int.from_bytes(u, "big")
    return acc.to_bytes(32, "big")


def _eq(a, b):
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= x ^ y
    return r == 0


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def gen_password(length, chars):
    out = []
    n = len(chars)
    limit = 256 - (256 % n)  # без смещения распределения
    while len(out) < length:
        for b in os.urandom(32):
            if b < limit and len(out) < length:
                out.append(chars[b % n])
    return "".join(out)


class Vault:
    def __init__(self, iterations):
        self.iterations = iterations
        self.entries = None   # list of [name, login, password]
        self._enc = None
        self._mac = None
        self._salt = None
        self._iters = iterations
        # восстановление после сбоя питания во время сохранения
        if not _exists(VAULT) and _exists(TMP):
            os.rename(TMP, VAULT)

    # ---------- состояние ----------
    def exists(self):
        return _exists(VAULT)

    @property
    def unlocked(self):
        return self.entries is not None

    def lock(self):
        self.entries = None
        self._enc = self._mac = None

    # ---------- ключи ----------
    def _derive(self, pin, salt, iters):
        dk = pbkdf2_sha256(pin.encode(), salt, iters)
        return hmac_sha256(dk, b"enc"), hmac_sha256(dk, b"mac")

    # ---------- операции ----------
    def create(self, pin):
        self._salt = os.urandom(16)
        self._iters = self.iterations
        self._enc, self._mac = self._derive(pin, self._salt, self._iters)
        self.entries = []
        self.save()

    def unlock(self, pin):
        with open(VAULT, "rb") as f:
            blob = f.read()
        if blob[:4] != MAGIC or len(blob) < 4 + 4 + 16 + 16 + 16 + 32:
            raise ValueError("vault corrupted")
        if (len(blob) - 72) % 16:
            raise ValueError("vault corrupted")
        iters = int.from_bytes(blob[4:8], "big")
        salt = blob[8:24]
        iv = blob[24:40]
        ct = blob[40:-32]
        tag = blob[-32:]
        enc, mac = self._derive(pin, salt, iters)
        if not _eq(hmac_sha256(mac, blob[:-32]), tag):
            return False
        pt = bytearray(len(ct))
        aesio.AES(enc, aesio.MODE_CBC, iv).decrypt_into(ct, pt)
        pad = pt[-1]
        if pad < 1 or pad > 16:
            raise ValueError("bad padding")
        self.entries = json.loads(bytes(pt[:-pad]).decode())
        self._enc, self._mac, self._salt, self._iters = enc, mac, salt, iters
        return True

    def save(self):
        data = json.dumps(self.entries).encode()
        pad = 16 - (len(data) % 16)
        data = data + bytes([pad]) * pad
        iv = os.urandom(16)
        ct = bytearray(len(data))
        aesio.AES(self._enc, aesio.MODE_CBC, iv).encrypt_into(data, ct)
        body = MAGIC + self._iters.to_bytes(4, "big") + self._salt + iv + ct
        blob = body + hmac_sha256(self._mac, body)
        with open(TMP, "wb") as f:
            f.write(blob)
        _remove(VAULT)
        os.rename(TMP, VAULT)

    def verify(self, pin):
        enc, _ = self._derive(pin, self._salt, self._iters)
        return _eq(enc, self._enc)

    def change_pin(self, new_pin):
        self._salt = os.urandom(16)
        self._iters = self.iterations
        self._enc, self._mac = self._derive(new_pin, self._salt, self._iters)
        self.save()

    def backup(self):
        with open(VAULT, "rb") as f:
            return f.read()

    def restore(self, blob):
        """Заменяет хранилище копией (после этого нужно разблокировать заново)."""
        if blob[:4] != MAGIC or len(blob) < 4 + 4 + 16 + 16 + 16 + 32 or (len(blob) - 72) % 16:
            raise ValueError("not a vault file")
        with open(TMP, "wb") as f:
            f.write(blob)
        _remove(VAULT)
        os.rename(TMP, VAULT)
        self.lock()

    def find(self, name):
        for i, e in enumerate(self.entries):
            if e[0] == name:
                return i
        return -1

    def wipe(self):
        _remove(VAULT)
        _remove(TMP)
        self.lock()

    # ---------- записи ----------
    def names(self):
        return [e[0] for e in self.entries]

    def put(self, name, login, password):
        for e in self.entries:
            if e[0] == name:
                e[1], e[2] = login, password
                return
        self.entries.append([name, login, password])
        self.entries.sort(key=lambda e: e[0].lower())

    def delete(self, index):
        self.entries.pop(index)

    def import_file(self, gen_len, gen_chars):
        """import.txt: по строке `имя;логин;пароль`. Пароль `*` = сгенерировать.
        Возвращает число импортированных записей, файл удаляется."""
        if not _exists(IMPORT):
            return 0
        n = 0
        with open(IMPORT, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(";", 2)
                if len(parts) != 3:
                    continue
                name, login, pw = parts[0].strip(), parts[1].strip(), parts[2]
                if pw == "*":
                    pw = gen_password(gen_len, gen_chars)
                if name:
                    self.put(name, login, pw)
                    n += 1
        self.save()
        _remove(IMPORT)
        return n

    # ---------- счётчик попыток ----------
    @staticmethod
    def get_attempts():
        try:
            with open(ATTEMPTS, "r") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    @staticmethod
    def set_attempts(n):
        if n == 0:
            _remove(ATTEMPTS)
            return
        with open(ATTEMPTS, "w") as f:
            f.write(str(n))
