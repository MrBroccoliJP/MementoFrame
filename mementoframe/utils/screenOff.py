import RPi.GPIO as GPIO
import time

# Use BCM numbering
GPIO.setmode(GPIO.BCM)
GPIO_PIN = 26

# Setup
GPIO.setup(GPIO_PIN, GPIO.OUT)

# Turn on
#GPIO.output(GPIO_PIN, GPIO.HIGH)
#print(f"GPIO{GPIO_PIN} set HIGH")

# Keep it on for 5 seconds
#time.sleep(5)

# Optional: turn off
GPIO.output(GPIO_PIN, GPIO.LOW)
print(f"GPIO{GPIO_PIN} set LOW")

#GPIO.cleanup()
