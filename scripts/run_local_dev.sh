#!/bin/bash
export ENV_MODE=dev
export FLASK_APP=dev_server.py
flask run --reload --port 8080