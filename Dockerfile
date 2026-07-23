# Use an official Python runtime as a parent image
FROM python:3.10

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install poetry
RUN pip install poetry

# Use poetry to install dependencies
RUN poetry config virtualenvs.create false \
  && poetry install --no-interaction --no-ansi

# Serve the local browser arcade on Gunicorn's application port.
EXPOSE 8000

# Keep one process because active game rounds live in memory. Threads allow
# concurrent local players while the file-backed leaderboard remains shared.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "brain_games.app:app"]
