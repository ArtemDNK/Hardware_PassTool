# Hardware PassTool

DIY аппаратный менеджер паролей на RP2040 — аналог Mooltipass Mini из того, что лежит в ящике:
плата RP2040, OLED 128×64 и джойстик.

Устройство подключается к компьютеру как **USB-клавиатура** и само печатает логин и пароль.
База хранится во флеше в зашифрованном виде, разблокируется PIN-ом прямо на устройстве.
Управлять записями можно с ПК (Python-утилита) или с телефона/ПК через браузер (веб-приложение).

## Возможности

- Ввод «логин → Tab → пароль → Enter», только пароля, только логина
- Русский интерфейс (пиксельный шрифт Cozette с кириллицей)
- AES-256-CBC + HMAC-SHA256, ключ из PIN через PBKDF2-HMAC-SHA256
- 10 неверных PIN подряд — хранилище стирается; растущая задержка между попытками
- Автоблокировка, гашение экрана
- Генератор паролей в утилите для ПК и в веб-приложении: длина, наборы символов, свои спецсимволы,
  исключение похожих символов (а также генерация на самом устройстве)
- Управление по USB: список, добавление, удаление, просмотр пароля, импорт CSV из браузеров/Bitwarden/KeePassXC, бэкап/восстановление
- Всё, что раскрывает секреты или удаляет данные, **подтверждается на устройстве**

## Железо и подключение

| Модуль          | Вывод | RP2040            |
|-----------------|-------|-------------------|
| OLED SSD1306    | VCC   | 3V3 (OUT)         |
|                 | GND   | GND               |
|                 | SDA   | GP4               |
|                 | SCL   | GP5               |
| Джойстик KY-023 | +5V   | **3V3**, не 5V!   |
|                 | GND   | GND               |
|                 | VRx   | GP26 (ADC0)       |
|                 | VRy   | GP27 (ADC1)       |
|                 | SW    | GP14              |

Джойстик питать строго от 3.3 В — иначе на АЦП придёт до 5 В.
Пины, тип экрана (SSD1306 / SH1106) и прочие настройки — в [`firmware/config.py`](firmware/config.py).

## Установка прошивки

1. Прошить [CircuitPython](https://circuitpython.org/downloads) 9 или 10 (UF2 для своей платы;
   для клона Pico на 16 МБ подойдёт сборка `VCC-GND YD-RP2040` или обычная `Raspberry Pi Pico`).
2. Поставить библиотеки в `/lib` (из Adafruit Bundle или через `circup`):
   ```
   circup install adafruit_hid adafruit_display_text adafruit_displayio_ssd1306 adafruit_bitmap_font
   ```
   Для экрана 1.3" — `adafruit_displayio_sh1106` и `DISPLAY_DRIVER = "sh1106"` в конфиге.
3. Скопировать на диск CIRCUITPY содержимое папки `firmware/`:
   `fonts/`, `config.py`, `vault.py`, `remote.py`, `code.py` и **последним** `boot.py`.
4. Переподключить USB. При первом запуске устройство попросит задать PIN.

## Режимы

- **Рабочий** (по умолчанию) — диск CIRCUITPY скрыт, есть USB-клавиатура и COM-порт для управления.
- **Обслуживание** — держать кнопку джойстика при подключении USB. Диск CIRCUITPY открыт:
  можно обновить прошивку, положить `import.txt`, забрать `vault.bin`.

## Управление на устройстве

| Действие             | Что делает |
|----------------------|------------|
| Вверх / вниз         | листать, менять символ PIN |
| Вправо или нажатие   | выбрать, добавить символ PIN |
| Влево                | назад, стереть символ PIN |
| Удержание (0.8 с)    | закончить ввод PIN; в меню — заблокировать |

## Управление с ПК — `pc/passtool.py`

```
pip install -r pc/requirements.txt
python pc/passtool.py status
python pc/passtool.py list
python pc/passtool.py add GitHub artem@example.com      # пароль спросит
python pc/passtool.py add Steam mylogin --gen           # сгенерировать пароль (20 символов, a-z A-Z 0-9 спецсимволы)
python pc/passtool.py add Bank me --gen -n 32 -c lud --show   # 32 символа без спецсимволов и показать
python pc/passtool.py add Wifi home --gen -c ld --no-ambiguous
python pc/passtool.py add Site me --gen -s "!#%-_"      # свой набор спецсимволов
python pc/passtool.py add Old me --gen-device           # сгенерировать на устройстве
python pc/passtool.py gen -n 16 --count 5               # просто сгенерировать, без устройства
python pc/passtool.py show GitHub                       # нужно подтвердить на устройстве
python pc/passtool.py rm GitHub                         # нужно подтвердить на устройстве
python pc/passtool.py import-csv passwords.csv          # экспорт Chrome/Edge/Яндекс/Firefox/Bitwarden/KeePassXC
python pc/passtool.py import-csv passwords.csv --dry-run
python pc/passtool.py backup vault.bin
python pc/passtool.py restore vault.bin
python pc/passtool.py lock
```

Порт ищется автоматически; можно указать вручную: `--port COM5` или `--port /dev/ttyACM0`.

Параметры генератора (`add --gen` и `gen`):

| Ключ | Что делает |
|------|------------|
| `-n`, `--length` | длина, по умолчанию 20 (до 128) |
| `-c`, `--charset` | группы: `l` — a-z, `u` — A-Z, `d` — 0-9, `s` — спецсимволы; по умолчанию `luds` |
| `-s`, `--symbols` | свой набор спецсимволов (печатные ASCII), по умолчанию `!@#$%^&*-_=+?.,:;()[]{}~` |
| `--no-ambiguous` | без похожих символов `I l 1 \| O 0 o ` ' "` |

В пароле всегда есть хотя бы один символ из каждой выбранной группы. Используется `secrets`
(в браузере — `crypto.getRandomValues`), без смещения распределения.

## Управление из браузера (ПК и Android) — `docs/index.html`

Одна страница без зависимостей, работает в Chrome / Edge. В форме добавления есть кнопка
«Сгенерировать» и настройки генератора (длина, a-z / A-Z / 0-9 / спецсимволы, свой набор
спецсимволов, без похожих символов); настройки запоминаются в браузере.

- **ПК** — кнопка «Подключить» (Web Serial).
- **Android** — Chrome + OTG-переходник, кнопка «через WebUSB».
  Web Serial на Android появляется только с Android 17, поэтому для остальных телефонов
  в странице реализован CDC-ACM поверх WebUSB. На некоторых прошивках телефонов ядро само
  захватывает USB-порт и WebUSB не может его открыть — тогда остаётся только ПК.

Страницу можно открыть локально или через GitHub Pages (Settings → Pages → ветка `main`, папка `/docs`).
Для WebUSB/Web Serial нужен HTTPS или `localhost`, поэтому с телефона удобнее через Pages.

## Добавление паролей файлом

В режиме обслуживания положить `import.txt` в корень CIRCUITPY (пример — [`examples/import.txt`](examples/import.txt)):
```
имя;логин;пароль
GitHub;artem@example.com;*      <- '*' = сгенерировать пароль на устройстве
```
После разблокировки в рабочем режиме записи зашифруются, а файл удалится.

## Протокол

JSON-строки по COM-порту, по одной на запрос/ответ:
```
-> {"id": 1, "cmd": "list"}
<- {"id": 1, "ok": true, "entries": [{"name": "GitHub", "login": "artem"}]}
```
Команды: `status`, `list`, `put` (`entries: [{name, login, password | gen}]`), `delete` (`name`),
`reveal` (`name`), `backup`, `restore` (`data` в base64), `lock`. Всё, кроме `status`, требует разблокировки.

## Безопасность — что важно понимать

- У RP2040 нет защищённого хранилища: флеш читается через BOOTSEL. Если устройство украдут,
  защита держится только на PIN + PBKDF2 → используйте длинный PIN (8–10+ символов),
  при желании добавьте буквы в `PIN_CHARS`.
- `import.txt` и CSV до импорта лежат открытым текстом — удаляйте их сразу.
- HID печатает скан-коды US-раскладки: перед вводом переключите раскладку ПК на английскую.
  Кириллица в логинах/паролях не печатается.
- Строки в MicroPython/CircuitPython нельзя надёжно затереть в памяти — расшифрованные данные
  живут в RAM, пока устройство разблокировано.

## Структура

```
firmware/   прошивка CircuitPython (копируется на CIRCUITPY)
  fonts/    шрифт Cozette (подмножество: ASCII + кириллица), лицензия MIT
pc/         утилита для ПК
docs/       веб-приложение (ПК + Android), годится для GitHub Pages
examples/   пример import.txt
tools/      скрипт сборки подмножества шрифта из cozette.bdf
```

## Благодарности

Шрифт [Cozette](https://github.com/the-moonwitch/Cozette) (MIT). Идея — [Mooltipass](https://github.com/mooltipass).
