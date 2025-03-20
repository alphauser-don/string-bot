#!/bin/sh

# Run database migrations
python -m database.migrate

# Start the application
exec python -m src.bot
