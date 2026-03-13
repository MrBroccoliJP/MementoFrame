#!/bin/bash
# activate virtualenv
source /home/mementoframe/mementoframe/venv/bin/activate

# run Python apps
python /home/mementoframe/mementoframe/app.py &
python /home/mementoframe/mementoframe/api_service.py &

# wait for all background processes
wait
