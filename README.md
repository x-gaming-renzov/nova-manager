# Nova Manager

A FastAPI-based application for managing nova experiences and campaigns.

## Features

- Feature flag management
- User experience personalization
- Campaign management
- Segment management
- Experience management

## Installation

See the Docker setup for containerized deployment.

poetry run python scripts/run_worker.py
uvicorn nova_manager.main:app --host 0.0.0.0 --reload
docker run -d --name redis -p 6379:6379 redis:latest