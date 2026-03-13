import RPi.GPIO as GPIO
import time

BRIGHTNESS_DOWN = 21
BRIGHTNESS_UP = 20
PRESS_DURATION = 5.5

GPIO.setmode(GPIO.BCM)

def press(pin, duration=PRESS_DURATION):
    # Only setup the pin you want to press
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
    print(f"Pressing GPIO {pin} for {duration}s")
    GPIO.output(pin, GPIO.LOW)
    time.sleep(duration)
    GPIO.output(pin, GPIO.HIGH)
    print("Released")
    GPIO.cleanup(pin)  # Only clean up that pin

try:
    while True:
        choice = input("Press [u]p, [d]own or [q]uit: ").lower()
        if choice == 'u':
            press(BRIGHTNESS_UP)
        elif choice == 'd':
            press(BRIGHTNESS_DOWN)
        elif choice == 'q':
            break
        else:
            print("Invalid input")
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
