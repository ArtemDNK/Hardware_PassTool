# Настройки железа и безопасности. Меняй пины здесь, а не в коде.
import board

# --- Экран (I2C) ---
I2C_SDA = board.GP4
I2C_SCL = board.GP5
DISPLAY_ADDR = 0x3C          # иногда 0x3D
DISPLAY_DRIVER = "ssd1306"   # "ssd1306" (0.96") или "sh1106" (1.3")
DISPLAY_W = 128
DISPLAY_H = 64
FONT_FILE = "/fonts/cozette_ru.bdf"

# --- Кнопки (тактовые, вторым выводом на GND; подтяжка внутренняя) ---
BTN_UP = board.GP13          # ▲
BTN_OK = board.GP14          # •  (зажать при подключении USB — режим обслуживания)
BTN_DOWN = board.GP15        # ▼

# --- PIN ---
PIN_CHARS = "0123456789"     # можно добавить буквы: "0123456789ABCDEF"
PIN_MIN_LEN = 6
PIN_MAX_LEN = 16
MAX_ATTEMPTS = 10            # после стольких ошибок подряд хранилище стирается

# --- Криптография ---
# Итерации PBKDF2. Больше = дольше разблокировка, но сложнее перебор дампа флеша.
# Действует только на новые хранилища / после смены PIN.
KDF_ITERATIONS = 10000

# --- Поведение ---
AUTOLOCK_S = 300             # автоблокировка при бездействии, секунд
SCREEN_OFF_S = 60            # гасить экран на экране PIN (защита OLED от выгорания)
TYPE_DELAY = 0.01            # задержка между символами при вводе
ENABLE_REPL = False          # в рабочем режиме оставить COM-порт с REPL (для отладки)
GEN_LENGTH = 20              # длина генерируемых паролей
GEN_CHARS = ("abcdefghijkmnopqrstuvwxyz"
             "ABCDEFGHJKLMNPQRSTUVWXYZ"
             "23456789"
             "!@#$%^&*-_=+?")

# --- USB ---
USB_MANUFACTURER = "DIY"
USB_PRODUCT = "Hardware PassTool"   # по этому имени утилиты находят устройство
