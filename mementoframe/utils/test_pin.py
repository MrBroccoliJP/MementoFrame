import RPi.GPIO as GPIO
import time

PIN = 20  # change to 21 if you want to test the other pin
PRESS_DURATION = 2  # seconds to keep it pressed

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)

try:
    print(f"Testing GPIO {PIN}...")
    while True:
        input("Press Enter to simulate button press...")

        # simulate press (active low)
        print("Pressing...")
        GPIO.output(PIN, GPIO.LOW)
        time.sleep(PRESS_DURATION)

        # release
        print("Releasing...")
        GPIO.output(PIN, GPIO.HIGH)
        time.sleep(0.1)

except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
    print("Cleaned up GPIOs")
