#!/usr/bin/env python3
import RPi.GPIO as GPIO, time
PIN = 24
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
print("Ctrl+C aby przerwać")
try:
    while True:
        val = GPIO.input(PIN)
        print("PIN=17:", val)
        time.sleep(0.2)
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
