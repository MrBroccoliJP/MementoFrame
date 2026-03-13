# MementoFrame - Raspberry Pi Smart Photo Frame
# Copyright (c) 2026 João Fernandes
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit:
# http://creativecommons.org/licenses/by-nc/4.0/

#This is used to start the necessary Python apps when the system boots up. It should be set to run at startup using a systemd service or similar mechanism.

#!/bin/bash
# activate virtualenv
source /home/mementoframe/mementoframe/venv/bin/activate

# run Python apps
python /home/mementoframe/mementoframe/app.py &
python /home/mementoframe/mementoframe/api_service.py &

# wait for all background processes
wait
