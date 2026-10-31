# Управление с ПК/телефона через COM-порт usb_cdc.data.
# Протокол: одна JSON-строка на запрос и одна на ответ, разделитель \n.
#   -> {"id": 1, "cmd": "list"}
#   <- {"id": 1, "ok": true, "entries": [{"name": "...", "login": "..."}]}
# Все команды, кроме status, работают только когда устройство разблокировано PIN-ом.
# Всё, что раскрывает секреты или уничтожает данные, подтверждается на самом устройстве.
import json
import binascii
import usb_cdc

PROTO = 1
MAX_LINE = 32768


class RemoteError(Exception):
    pass


class Remote:
    def __init__(self, vault, confirm, locked_exc, gen):
        self.vault = vault
        self.confirm = confirm          # confirm(text) -> bool, показывает вопрос на экране
        self.locked_exc = locked_exc    # исключение блокировки из UI
        self.gen = gen                  # gen() -> новый случайный пароль
        self.ser = usb_cdc.data
        if self.ser:
            self.ser.timeout = 0
            self.ser.write_timeout = 2
        self.buf = b""
        self.busy = False
        self.changed = False            # данные изменены -> UI должен перерисовать список
        self.lock_request = False       # нужно заблокировать устройство

    def poll(self):
        """Обработать входящие команды. Возвращает True, если что-то обработано."""
        if self.ser is None or self.busy:
            return False
        n = self.ser.in_waiting
        if not n:
            return False
        self.buf += self.ser.read(n)
        if len(self.buf) > MAX_LINE:
            self.buf = b""
            self._send({"ok": False, "err": "too_long"})
            return True
        handled = False
        while True:
            i = self.buf.find(b"\n")
            if i < 0:
                break
            line = self.buf[:i].strip()
            self.buf = self.buf[i + 1:]
            if line:
                self._handle(line)
                handled = True
        return handled

    def _send(self, obj):
        try:
            self.ser.write((json.dumps(obj) + "\n").encode())
        except Exception:  # noqa  хост отключился / не читает
            pass

    def _handle(self, line):
        self.busy = True
        rid = None
        try:
            req = json.loads(line.decode())
            rid = req.get("id")
            cmd = req.get("cmd", "")
            fn = getattr(self, "cmd_" + cmd, None)
            if fn is None:
                raise RemoteError("unknown_cmd")
            if cmd != "status" and not self.vault.unlocked:
                raise RemoteError("locked")
            resp = fn(req) or {}
            resp["ok"] = True
        except RemoteError as e:
            resp = {"ok": False, "err": str(e)}
        except Exception as e:  # noqa
            if isinstance(e, self.locked_exc):
                self._send({"id": rid, "ok": False, "err": "locked"})
                self.busy = False
                raise
            resp = {"ok": False, "err": repr(e)}
        resp["id"] = rid
        self._send(resp)
        self.busy = False

    def _ask(self, text):
        if not self.confirm(text):
            raise RemoteError("denied")

    # ---------------- команды ----------------
    def cmd_status(self, req):
        v = self.vault
        return {"device": "passtool", "proto": PROTO, "unlocked": v.unlocked,
                "count": len(v.entries) if v.unlocked else None}

    def cmd_list(self, req):
        return {"entries": [{"name": e[0], "login": e[1]} for e in self.vault.entries]}

    def cmd_put(self, req):
        items = req.get("entries") or []
        clean = []
        for it in items:
            name = str(it.get("name", "")).strip()
            if not name:
                raise RemoteError("empty_name")
            pw = it.get("password")
            if it.get("gen") or not pw:
                pw = self.gen()
            clean.append((name, str(it.get("login", "")), str(pw)))
        exist = [c[0] for c in clean if self.vault.find(c[0]) >= 0]
        if exist:
            q = "Перезаписать «%s»?" % exist[0] if len(exist) == 1 \
                else "Перезаписать %d записей?" % len(exist)
            self._ask(q)
        for name, login, pw in clean:
            self.vault.put(name, login, pw)
        self.vault.save()
        self.changed = True
        return {"added": len(clean) - len(exist), "updated": len(exist)}

    def _index(self, req):
        i = self.vault.find(str(req.get("name", "")))
        if i < 0:
            raise RemoteError("not_found")
        return i

    def cmd_delete(self, req):
        i = self._index(req)
        self._ask("Удалить «%s» по запросу ПК?" % self.vault.entries[i][0])
        self.vault.delete(i)
        self.vault.save()
        self.changed = True

    def cmd_reveal(self, req):
        i = self._index(req)
        e = self.vault.entries[i]
        self._ask("Отдать пароль «%s» на ПК?" % e[0])
        return {"name": e[0], "login": e[1], "password": e[2]}

    def cmd_backup(self, req):
        self._ask("Отдать зашифр. копию хранилища на ПК?")
        data = binascii.b2a_base64(self.vault.backup()).strip().decode()
        return {"data": data}

    def cmd_restore(self, req):
        blob = binascii.a2b_base64(req.get("data", ""))
        self._ask("Заменить хранилище копией с ПК? Текущее пропадёт!")
        try:
            self.vault.restore(blob)
        except ValueError:
            raise RemoteError("bad_file")
        self.lock_request = True

    def cmd_lock(self, req):
        self.lock_request = True
