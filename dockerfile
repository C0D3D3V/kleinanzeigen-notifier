# Basisimage
FROM python:3.11-slim

# Setze Arbeitsverzeichnis innerhalb des Containers
WORKDIR /app

# Kopiere requirements.txt in das Arbeitsverzeichnis
COPY requirements.txt .

# Installiere Abhängigkeiten
RUN pip install -r requirements.txt

# Kopiere den gesamten aktuellen Code in das Arbeitsverzeichnis
COPY . .

# Umgebungsvariablen setzen (kann auch im docker-compose.yml gesetzt werden)
ENV KN_PATH /app/data
ENV KN_PARALLEL_DOWNLOADS 10

# Startbefehl für das Python-Skript
CMD ["python", "./kleinanzeigen_notifier.py"]