# Hardware PassTool — DIY аппаратный менеджер паролей на RP2040 (аналог Mooltipass Mini).
# Экран SSD1306/SH1106 128x64 I2C + три тактовые кнопки: ▲, ▼ и • (OK).
# Устройство притворяется USB-клавиатурой и печатает логин/пароль,
# а через отдельный COM-порт им можно управлять с ПК или телефона.
import time
import busio
import digitalio
import displayio
import storage
import supervisor
import usb_hid

from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from adafruit_hid.keycode import Keycode

import config
from vault import Vault, gen_password
from remote import Remote

supervisor.runtime.autoreload = False
MAINTENANCE = storage.getmount("/").readonly
COLS = 21          # символов в строке (шрифт 6 px)
ROWS = 5           # строк на экране 64 px
LINE_H = 13


# ===================== Экран =====================
displayio.release_displays()
_i2c = busio.I2C(config.I2C_SCL, config.I2C_SDA, frequency=400000)
try:
    from i2cdisplaybus import I2CDisplayBus           # CircuitPython 9+
except ImportError:
    from displayio import I2CDisplay as I2CDisplayBus  # CircuitPython 8
_bus = I2CDisplayBus(_i2c, device_address=config.DISPLAY_ADDR)
if config.DISPLAY_DRIVER == "sh1106":
    import adafruit_displayio_sh1106 as _drv
    display = _drv.SH1106(_bus, width=config.DISPLAY_W, height=config.DISPLAY_H)
else:
    import adafruit_displayio_ssd1306 as _drv
    display = _drv.SSD1306(_bus, width=config.DISPLAY_W, height=config.DISPLAY_H)

FONT = bitmap_font.load_font(config.FONT_FILE)
FONT.load_glyphs(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя«»—→…•▲▼"
)

_group = displayio.Group()
_lines = []
for i in range(ROWS):
    lb = label.Label(FONT, text=" ", color=0xFFFFFF, padding_right=config.DISPLAY_W,
                     anchor_point=(0, 0), anchored_position=(0, i * LINE_H))
    _group.append(lb)
    _lines.append(lb)
try:
    display.root_group = _group
except AttributeError:
    display.show(_group)

_screen_on = True


def screen(lines, highlight=None):
    if not _screen_on:
        screen_wake()
    for i in range(ROWS):
        t = lines[i] if i < len(lines) else ""
        lb = _lines[i]
        lb.text = t[:COLS] or " "
        if i == highlight:
            lb.color, lb.background_color = 0x000000, 0xFFFFFF
        else:
            lb.color, lb.background_color = 0xFFFFFF, None


def screen_wake():
    global _screen_on
    display.wake()
    _screen_on = True


def screen_off():
    global _screen_on
    if _screen_on:
        display.sleep()
        _screen_on = False


def wrap(text, width=COLS):
    """Перенос по словам; слишком длинные слова режутся."""
    out = []
    line = ""
    for word in str(text).split(" "):
        while len(word) > width:
            if line:
                out.append(line)
                line = ""
            out.append(word[:width])
            word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            out.append(line)
            line = word
    if line or not out:
        out.append(line)
    return out


def chunks(text, width=COLS):
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


# ===================== Кнопки =====================
class Locked(Exception):
    pass


class Refresh(Exception):
    """Данные изменены с ПК — вернуться к списку и перерисовать."""
    pass


class Buttons:
    """Три кнопки на землю (внутренняя подтяжка). События:
    U / D   — нажатие ▲ / ▼ (при удержании — автоповтор)
    OK      — короткое нажатие •
    LONG    — удержание • (назад; в PIN — готово)
    BOTH    — ▲ и ▼ вместе (блокировка; в PIN — стереть символ)
    """
    LONG = 0.8
    REPEAT_DELAY = 0.45
    REPEAT_RATE = 0.12
    DEBOUNCE = 0.02

    def __init__(self):
        self.io = {}
        for name, pin in (("U", config.BTN_UP), ("D", config.BTN_DOWN), ("OK", config.BTN_OK)):
            b = digitalio.DigitalInOut(pin)
            b.switch_to_input(pull=digitalio.Pull.UP)
            self.io[name] = b
        self.raw = {n: False for n in self.io}         # последнее сырое значение
        self.raw_t = {n: 0.0 for n in self.io}         # когда оно поменялось
        self.state = {n: False for n in self.io}       # состояние после антидребезга
        self.ok_t = 0.0
        self.long_sent = False
        self.rep_t = 0.0
        self.repeating = False
        self.chord = False

    def _read(self, now):
        cur = {}
        for n, b in self.io.items():
            v = not b.value
            if v != self.raw[n]:
                self.raw[n], self.raw_t[n] = v, now
            cur[n] = self.raw[n] if now - self.raw_t[n] >= self.DEBOUNCE else self.state[n]
        return cur

    def poll(self):
        now = time.monotonic()
        cur = self._read(now)
        prev = self.state
        self.state = cur
        # ▲+▼ вместе
        if cur["U"] and cur["D"]:
            if not self.chord:
                self.chord = True
                return "BOTH"
            return None
        if self.chord:
            if not cur["U"] and not cur["D"]:
                self.chord = False
            return None
        # ▲ / ▼ с автоповтором
        for n in ("U", "D"):
            if cur[n] and not prev[n]:
                self.rep_t, self.repeating = now, False
                return n
            if cur[n]:
                wait = self.REPEAT_RATE if self.repeating else self.REPEAT_DELAY
                if now - self.rep_t >= wait:
                    self.rep_t, self.repeating = now, True
                    return n
        # • короткое / долгое
        if cur["OK"] and not prev["OK"]:
            self.ok_t, self.long_sent = now, False
        elif cur["OK"] and not self.long_sent and now - self.ok_t >= self.LONG:
            self.long_sent = True
            return "LONG"
        elif not cur["OK"] and prev["OK"] and not self.long_sent:
            return "OK"
        return None


buttons = Buttons()
vault = Vault(config.KDF_ITERATIONS)
_last_activity = time.monotonic()


def _gen():
    return gen_password(config.GEN_LENGTH, config.GEN_CHARS)


def wait_event(lock_screen=False):
    """Ждёт нажатие кнопки, попутно обслуживает команды с ПК и автоблокировку."""
    global _last_activity
    while True:
        if remote.poll():
            _last_activity = time.monotonic()
        if not remote.busy:
            if remote.lock_request:
                remote.lock_request = False
                raise Locked()
            if remote.changed:
                remote.changed = False
                raise Refresh()
        ev = buttons.poll()
        now = time.monotonic()
        if ev:
            _last_activity = now
            if not _screen_on:
                screen_wake()
                continue  # первое касание только будит экран
            return ev
        idle = now - _last_activity
        if vault.unlocked and idle > config.AUTOLOCK_S:
            raise Locked()
        if lock_screen and idle > config.SCREEN_OFF_S:
            screen_off()
        time.sleep(0.01)


# ===================== Клавиатура =====================
_kbd = None
_layout = None


def keyboard():
    global _kbd, _layout
    if _kbd is None:
        _kbd = Keyboard(usb_hid.devices)
        _layout = KeyboardLayoutUS(_kbd)
    return _kbd, _layout


def type_seq(parts):
    """parts: список строк и Keycode (int)."""
    screen(["", "   Печатаю...", "", "Раскладка ПК должна", "быть английской!"])
    time.sleep(0.3)
    try:
        kbd, layout = keyboard()
        for p in parts:
            if isinstance(p, int):
                kbd.send(p)
                time.sleep(0.05)
            else:
                layout.write(p, delay=config.TYPE_DELAY)
    except ValueError:
        message(["Ошибка: в логине", "или пароле есть", "символ не из ASCII"])
    except OSError:
        message(["USB не готов"])


# ===================== Виджеты =====================
def message(lines):
    rows = list(lines[:ROWS - 1])
    while len(rows) < ROWS - 1:
        rows.append("")
    rows.append("         [OK]")
    screen(rows)
    while wait_event() not in ("OK", "LONG"):
        pass


def confirm(question):
    idx = 1
    lines = wrap(question)[:3]
    while len(lines) < 3:
        lines.append("")
    while True:
        screen(lines + [" Да", " Нет"], highlight=3 + idx)
        ev = wait_event()
        if ev in ("U", "D"):
            idx ^= 1
        elif ev == "OK":
            return idx == 0
        elif ev == "LONG":
            return False


def menu(title, items, idx=0):
    """Возвращает индекс выбранного пункта или None (удержание • — назад).
    ▲+▼ вместе — блокировка."""
    if not items:
        return None
    view = ROWS - 1
    while True:
        idx %= len(items)
        top = max(0, min(idx - view + 1, len(items) - view))
        rows = [title[:COLS]]
        for i in range(top, min(top + view, len(items))):
            rows.append(" " + items[i])
        screen(rows, highlight=1 + idx - top)
        ev = wait_event()
        if ev == "U":
            idx -= 1
        elif ev == "D":
            idx += 1
        elif ev == "OK":
            return idx
        elif ev == "LONG":
            return None
        elif ev == "BOTH" and vault.unlocked:
            raise Locked()


def pin_entry(title, lock_screen=True):
    """▲/▼ — символ, • — добавить, ▲+▼ — стереть, удержание • — готово."""
    chars = config.PIN_CHARS
    entered = []
    cur = 0
    while True:
        shown = "*" * len(entered)
        if len(entered) < config.PIN_MAX_LEN:
            shown += "[" + chars[cur] + "]"
        hint = "удерж. • — готово" if len(entered) >= config.PIN_MIN_LEN \
            else "минимум %d симв." % config.PIN_MIN_LEN
        screen([title, "", " " + shown, "▲+▼ — стереть", hint])
        ev = wait_event(lock_screen=lock_screen)
        if ev == "U":
            cur = (cur + 1) % len(chars)
        elif ev == "D":
            cur = (cur - 1) % len(chars)
        elif ev == "OK":
            if len(entered) < config.PIN_MAX_LEN:
                entered.append(chars[cur])
                cur = 0
        elif ev == "BOTH":
            if entered:
                entered.pop()
        elif ev == "LONG":
            if len(entered) >= config.PIN_MIN_LEN:
                return "".join(entered)


def new_pin():
    while True:
        p1 = pin_entry("Новый PIN:")
        p2 = pin_entry("Повторите PIN:")
        if p1 == p2:
            return p1
        message(["PIN не совпадают,", "попробуйте ещё раз"])


def busy(text):
    screen(["", "  " + text, "", "  подождите..."])


remote = Remote(vault, confirm, Locked, _gen)


# ===================== Сценарии =====================
def setup_new():
    message(["Хранилища нет.", "Создадим новое.", "Удержание • —", "конец ввода PIN."])
    pin = new_pin()
    busy("Создаю...")
    vault.create(pin)
    Vault.set_attempts(0)


def unlock():
    while True:
        attempts = Vault.get_attempts()
        left = config.MAX_ATTEMPTS - attempts
        title = "Введите PIN:" if attempts == 0 else "PIN (осталось %d):" % left
        pin = pin_entry(title)
        busy("Проверяю...")
        # счётчик пишем ДО проверки: выдёргивание питания не сбросит попытку
        attempts += 1
        Vault.set_attempts(attempts)
        try:
            ok = vault.unlock(pin)
        except ValueError as e:
            message(["Ошибка хранилища:"] + wrap(str(e))[:2])
            ok = False
        if ok:
            Vault.set_attempts(0)
            return
        if attempts >= config.MAX_ATTEMPTS:
            vault.wipe()
            Vault.set_attempts(0)
            message(["Слишком много", "попыток.", "ХРАНИЛИЩЕ СТЁРТО."])
            return
        delay = min(2 ** attempts, 60)
        screen(["Неверный PIN!", "", "ждите %d с" % delay])
        time.sleep(delay)


def do_import():
    try:
        n = vault.import_file(config.GEN_LENGTH, config.GEN_CHARS)
    except Exception as e:  # noqa
        message(["Ошибка импорта:"] + wrap(str(e))[:2])
        return
    if n:
        message(["Импортировано: %d" % n, "import.txt удалён"])


def show_entry(e):
    message(chunks("Л:" + e[1])[:1] + chunks("П:" + e[2])[:3])


def entry_menu(i):
    e = vault.entries[i]
    T, E = Keycode.TAB, Keycode.ENTER
    actions = [
        ("Логин→Пароль→Enter", lambda: type_seq([e[1], T, e[2], E])),
        ("Логин→Пароль", lambda: type_seq([e[1], T, e[2]])),
        ("Пароль→Enter", lambda: type_seq([e[2], E])),
        ("Пароль", lambda: type_seq([e[2]])),
        ("Логин", lambda: type_seq([e[1]])),
        ("Показать", lambda: show_entry(e)),
        ("Удалить", None),
    ]
    idx = 0
    while True:
        idx = menu(e[0], [a[0] for a in actions], idx)
        if idx is None:
            return
        name, fn = actions[idx]
        if fn is None:
            if confirm("Удалить «%s»?" % e[0]):
                vault.delete(i)
                vault.save()
                return
        else:
            fn()
            if idx < 5:   # после ввода сразу назад к списку
                return


def browse():
    idx = 0
    while True:
        names = vault.names()
        items = names + ["[Заблокировать]", "[Сменить PIN]"]
        title = "Пароли (%d)" % len(names)
        idx = menu(title, items, idx)
        if idx is None:      # удержание • в главном списке — заблокировать
            raise Locked()
        if idx < len(names):
            entry_menu(idx)
        elif idx == len(names):
            raise Locked()
        else:
            old = pin_entry("Текущий PIN:")
            busy("Проверяю...")
            if not vault.verify(old):
                message(["Неверный PIN"])
                continue
            pin = new_pin()
            busy("Перешифровываю...")
            vault.change_pin(pin)
            message(["PIN изменён"])


def maintenance_screen():
    screen(["РЕЖИМ ОБСЛУЖИВАНИЯ", "Флешка открыта:", "import.txt, бэкап", "vault.bin, код.", "Переподключи USB"])
    while True:
        time.sleep(1)


def main():
    if MAINTENANCE:
        maintenance_screen()
    while True:
        try:
            if not vault.exists():
                setup_new()
            if not vault.unlocked:
                unlock()
                if not vault.unlocked:
                    continue
            do_import()
            browse()
        except Locked:
            vault.lock()
        except Refresh:
            pass


try:
    main()
except Exception as ex:  # REPL выключен, поэтому показываем ошибку на экране
    vault.lock()
    screen(["ОШИБКА:"] + chunks(repr(ex))[:4])
    while True:
        time.sleep(1)
