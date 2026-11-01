# Выполняется при старте до code.py.
# Кнопка CONFIRM зажата при подключении -> режим обслуживания:
#   флешка CIRCUITPY видна на ПК, можно обновить код, положить import.txt, забрать vault.bin.
# Иначе -> рабочий режим: флешка скрыта, код может писать в хранилище,
#   включены USB-клавиатура и отдельный COM-порт для утилит управления.
import time
import digitalio
import storage
import supervisor
import usb_cdc
import usb_hid
import config

btn = digitalio.DigitalInOut(config.BTN_CONFIRM)
btn.switch_to_input(pull=digitalio.Pull.UP)
time.sleep(0.05)
maintenance = not btn.value
btn.deinit()

try:
    supervisor.set_usb_identification(config.USB_MANUFACTURER, config.USB_PRODUCT)
except (AttributeError, RuntimeError):
    pass

usb_hid.enable((usb_hid.Device.KEYBOARD,))

if maintenance:
    usb_cdc.enable(console=True, data=False)
else:
    storage.disable_usb_drive()
    storage.remount("/", readonly=False)
    usb_cdc.enable(console=config.ENABLE_REPL, data=True)
