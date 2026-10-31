#!/usr/bin/env python3
"""Hardware PassTool — утилита управления устройством с ПК.

Устройство должно быть подключено в рабочем режиме и разблокировано PIN-ом.
Операции, раскрывающие секреты или удаляющие данные, нужно подтвердить на устройстве.

Примеры:
    python passtool.py status
    python passtool.py list
    python passtool.py add GitHub artem@example.com          # пароль спросит
    python passtool.py add Steam mylogin --gen               # сгенерирует устройство
    python passtool.py show GitHub
    python passtool.py rm GitHub
    python passtool.py import-csv chrome_passwords.csv
    python passtool.py backup vault.bin
    python passtool.py restore vault.bin
"""
import argparse
import base64
import csv
import getpass
import json
import sys
import time
from urllib.parse import urlparse

import serial
from serial.tools import list_ports

PRODUCT = "Hardware PassTool"
KNOWN_VIDS = {0x239A, 0x2E8A}   # Adafruit / CircuitPython, Raspberry Pi
CONFIRM_TIMEOUT = 90            # сколько ждать подтверждения на устройстве, с
ERRORS = {
    "locked": "устройство заблокировано — введите PIN на нём",
    "denied": "отклонено на устройстве",
    "not_found": "запись не найдена",
    "bad_file": "файл не похож на хранилище",
    "empty_name": "пустое имя записи",
    "too_long": "слишком большой запрос",
    "unknown_cmd": "устройство не знает такую команду (обновите прошивку)",
}


class DeviceError(Exception):
    pass


class Device:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.2, write_timeout=5)
        try:
            self.ser.dtr = True
        except (OSError, serial.SerialException):
            pass
        self._id = 0
        self._buf = b""

    def close(self):
        self.ser.close()

    def call(self, cmd, timeout=5, **kw):
        self._id += 1
        rid = self._id
        req = dict(kw, cmd=cmd, id=rid)
        self.ser.write((json.dumps(req, ensure_ascii=False) + "\n").encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                try:
                    resp = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue  # мусор (например, вывод REPL)
                if not isinstance(resp, dict) or resp.get("id") != rid:
                    continue
                if not resp.get("ok"):
                    err = resp.get("err", "?")
                    raise DeviceError(ERRORS.get(err, err))
                return resp
        raise DeviceError("нет ответа от устройства (таймаут)")


def candidate_ports():
    ports = list(list_ports.comports())
    named = [p for p in ports if (p.product or "") == PRODUCT
             or PRODUCT in (p.description or "")]
    known = [p for p in ports if p.vid in KNOWN_VIDS and p not in named]
    return [p.device for p in named + known]


def find_device(port=None):
    ports = [port] if port else candidate_ports()
    if not ports:
        raise DeviceError("устройство не найдено. Подключено ли оно в рабочем режиме? "
                          "Порт можно указать вручную: --port COM5")
    for p in ports:
        try:
            dev = Device(p)
        except serial.SerialException:
            continue
        try:
            st = dev.call("status", timeout=1.5)
            if st.get("device") == "passtool":
                return dev, st
        except DeviceError:
            pass
        dev.close()
    raise DeviceError("ни один порт не ответил как PassTool (проверены: %s)" % ", ".join(ports))


# ---------------- CSV ----------------
NAME_KEYS = ("name", "title", "название")
LOGIN_KEYS = ("username", "login_username", "login", "user", "email", "логин")
PASS_KEYS = ("password", "login_password", "pass", "пароль")
URL_KEYS = ("url", "login_uri", "uri", "website", "origin_url")


def _pick(row, keys):
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for k in keys:
        if low.get(k):
            return low[k].strip() if k not in PASS_KEYS else low[k]
    return ""


def read_csv(path):
    """Понимает экспорт Chrome/Edge/Яндекс.Браузера, Firefox, Bitwarden, KeePassXC."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        pw = _pick(r, PASS_KEYS)
        if not pw:
            continue
        name = _pick(r, NAME_KEYS)
        url = _pick(r, URL_KEYS)
        if not name and url:
            name = urlparse(url if "://" in url else "https://" + url).hostname or url
        name = (name or "").removeprefix("www.")
        if not name:
            continue
        out.append({"name": name, "login": _pick(r, LOGIN_KEYS), "password": pw})
    # одинаковые имена — добавляем логин, чтобы записи не затирали друг друга
    seen = {}
    for e in out:
        seen[e["name"]] = seen.get(e["name"], 0) + 1
    for e in out:
        if seen[e["name"]] > 1 and e["login"]:
            e["name"] = "%s (%s)" % (e["name"], e["login"])
    return out


# ---------------- команды ----------------
def non_ascii(s):
    return any(ord(c) > 126 or ord(c) < 32 for c in s)


def cmd_status(dev, st, a):
    if st["unlocked"]:
        print("Устройство разблокировано, записей: %d" % st["count"])
    else:
        print("Устройство заблокировано — введите PIN на нём")


def cmd_list(dev, st, a):
    entries = dev.call("list")["entries"]
    if not entries:
        print("(пусто)")
        return
    w = max(len(e["name"]) for e in entries)
    for e in entries:
        print("%-*s  %s" % (w, e["name"], e["login"]))
    print("\nВсего: %d" % len(entries))


def cmd_add(dev, st, a):
    item = {"name": a.name, "login": a.login or ""}
    if a.gen:
        item["gen"] = True
    else:
        pw = a.password or getpass.getpass("Пароль для %s: " % a.name)
        if not a.password and pw != getpass.getpass("Ещё раз: "):
            raise DeviceError("пароли не совпадают")
        if non_ascii(pw) or non_ascii(item["login"]):
            print("Внимание: не-ASCII символы устройство не сможет напечатать.")
        item["password"] = pw
    print("Если запись уже есть — подтвердите перезапись на устройстве...")
    r = dev.call("put", timeout=CONFIRM_TIMEOUT, entries=[item])
    print("Готово (новых: %d, обновлено: %d)" % (r["added"], r["updated"]))


def cmd_show(dev, st, a):
    print("Подтвердите на устройстве...")
    r = dev.call("reveal", timeout=CONFIRM_TIMEOUT, name=a.name)
    print("Логин:  %s\nПароль: %s" % (r["login"], r["password"]))


def cmd_rm(dev, st, a):
    print("Подтвердите удаление на устройстве...")
    dev.call("delete", timeout=CONFIRM_TIMEOUT, name=a.name)
    print("Удалено")


def cmd_import_csv(dev, st, a):
    entries = read_csv(a.file)
    if not entries:
        raise DeviceError("в файле не нашлось записей с паролями")
    bad = [e["name"] for e in entries if non_ascii(e["password"]) or non_ascii(e["login"])]
    print("Найдено записей: %d" % len(entries))
    if bad:
        print("С не-ASCII символами (не напечатаются): " + ", ".join(bad[:10])
              + (" ..." if len(bad) > 10 else ""))
    if a.dry_run:
        for e in entries:
            print("  %s  %s" % (e["name"], e["login"]))
        return
    added = updated = 0
    for i in range(0, len(entries), a.batch):
        part = entries[i:i + a.batch]
        r = dev.call("put", timeout=CONFIRM_TIMEOUT, entries=part)
        added += r["added"]
        updated += r["updated"]
        print("  %d/%d" % (min(i + a.batch, len(entries)), len(entries)))
    print("Готово (новых: %d, обновлено: %d)" % (added, updated))
    print("Не забудьте удалить CSV — пароли в нём открытым текстом!")


def cmd_backup(dev, st, a):
    print("Подтвердите на устройстве...")
    r = dev.call("backup", timeout=CONFIRM_TIMEOUT)
    data = base64.b64decode(r["data"])
    with open(a.file, "wb") as f:
        f.write(data)
    print("Сохранено %d байт в %s (файл зашифрован PIN-ом)" % (len(data), a.file))


def cmd_restore(dev, st, a):
    with open(a.file, "rb") as f:
        data = f.read()
    if data[:4] != b"DPV1":
        raise DeviceError("это не файл хранилища PassTool")
    print("Подтвердите замену на устройстве...")
    dev.call("restore", timeout=CONFIRM_TIMEOUT, data=base64.b64encode(data).decode())
    print("Хранилище заменено. Устройство заблокировано — введите PIN от этой копии.")


def cmd_lock(dev, st, a):
    dev.call("lock")
    print("Заблокировано")


def main():
    p = argparse.ArgumentParser(description="Управление Hardware PassTool")
    p.add_argument("--port", help="COM-порт устройства (по умолчанию — автопоиск)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="состояние устройства")
    sub.add_parser("list", help="список записей (без паролей)")
    s = sub.add_parser("add", help="добавить/изменить запись")
    s.add_argument("name")
    s.add_argument("login", nargs="?", default="")
    s.add_argument("--gen", action="store_true", help="сгенерировать пароль на устройстве")
    s.add_argument("--password", help="пароль (небезопасно: останется в истории shell)")
    s = sub.add_parser("show", help="показать пароль (с подтверждением)")
    s.add_argument("name")
    s = sub.add_parser("rm", help="удалить запись (с подтверждением)")
    s.add_argument("name")
    s = sub.add_parser("import-csv", help="импорт из CSV браузера/Bitwarden/KeePassXC")
    s.add_argument("file")
    s.add_argument("--batch", type=int, default=10, help="записей за запрос")
    s.add_argument("--dry-run", action="store_true", help="только показать, что будет импортировано")
    s = sub.add_parser("backup", help="скачать зашифрованную копию хранилища")
    s.add_argument("file")
    s = sub.add_parser("restore", help="загрузить копию хранилища на устройство")
    s.add_argument("file")
    sub.add_parser("lock", help="заблокировать устройство")
    a = p.parse_args()

    if a.cmd == "import-csv" and a.dry_run:
        cmd_import_csv(None, None, a)
        return
    try:
        dev, st = find_device(a.port)
    except DeviceError as e:
        sys.exit("Ошибка: %s" % e)
    try:
        if a.cmd != "status" and not st["unlocked"]:
            raise DeviceError(ERRORS["locked"])
        globals()["cmd_" + a.cmd.replace("-", "_")](dev, st, a)
    except DeviceError as e:
        sys.exit("Ошибка: %s" % e)
    except KeyboardInterrupt:
        sys.exit(1)
    finally:
        dev.close()


if __name__ == "__main__":
    main()
