# Настройки железа и безопасности. Меняй пины здесь, а не в коде.
import board

# --- Экран (I2C) ---
I2C_SDA = board.GP4
I2C_SCL = board.GP5
DISPLAY_ADDR = 0x3C          # иногда 0x3D
DISPLAY_DRIVER = "sh1106"    # "sh1106" (1.3") или "ssd1306" (0.96")
DISPLAY_W = 128
DISPLAY_H = 64
FONT_FILE = "/fonts/cozette_ru.bdf"

# --- Энкодер EC11 и кнопки (модуль OLED 1.3" + EC11) ---
# ENC_A и ENC_B на RP2040 должны быть соседними пинами (GPn и GPn+1).
ENC_A = board.GP10           # TRA
ENC_B = board.GP11           # TRB
ENC_DIVISOR = 4              # переходов на щелчок: если щелчок листает на 2 пункта — 2→4, если через раз — 4→2
ENC_REVERSE = False          # если по часовой листает вверх
ENC_PUSH = board.GP12        # PSH — нажатие энкодера (= CONFIRM)
BTN_CONFIRM = board.GP13     # CON (зажать при подключении USB — режим обслуживания)
BTN_BACK = board.GP14        # BAK

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
