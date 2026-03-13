import RPi.GPIO as GPIO
import time

BRIGHTNESS_DOWN = 21
BRIGHTNESS_UP = 20
PRESS_DURATION = 5.5
STEP_DELAY = 0.5  # 0.5s per brightness level

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

def set_brightness(level):
    """
    Reset brightness to 0 (hold down 5.5s),
    then press UP with 0.5s delay per level.
    """
    level = max(0, min(100, int(level)))  # Clamp range
    print(f"\nSetting brightness to {level}/10")

    # Reset to minimum
    press(BRIGHTNESS_DOWN, PRESS_DURATION)
    GPIO.cleanup(BRIGHTNESS_DOWN)
    time.sleep(0.5)

    # Increase brightness in steps
    for i in range(level):
        print(f"Step {i+1}/{level}")
        press(BRIGHTNESS_UP, 0.5)   # short tap
        time.sleep(STEP_DELAY - 0.1)  # ensure total interval ≈0.5s

    print(f"Brightness set to {level}")

try:
    while True:
        choice = input("Set brightness (0–10) or [q]uit: ").strip().lower()
        if choice == 'q':
            break
        try:
            level = int(choice)
            set_brightness(level)
        except ValueError:
            print("Invalid input. Enter a number 0–10 or 'q'.")
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
