# Dockerfile für projekt_aggregator.py
#
# Build:
#   docker build -t projekt-aggregator ./tools
#
# Verwendung:
#   docker run --rm -v $(pwd):/project projekt-aggregator
#   docker run --rm -v $(pwd):/project projekt-aggregator --output mein_projekt.md
#   docker run --rm -v $(pwd):/project projekt-aggregator --extensions .py,.md --ignore node_modules
#
# Mit Projektbeschreibung aus Datei (im Projektverzeichnis):
#   docker run --rm -v $(pwd):/project projekt-aggregator --description @beschreibung.txt
#
# Mit Projektbeschreibung aus externem Verzeichnis:
#   docker run --rm -v $(pwd):/project -v /pfad/zu/config:/config projekt-aggregator --description @/config/beschreibung.txt
#
# Ausgabe nach stdout:
#   docker run --rm -v $(pwd):/project projekt-aggregator --output - > projekt.md
#
# KI-Prompt für Projektbeschreibung generieren:
#   docker run --rm -v $(pwd):/project projekt-aggregator --generate-prompt
#

FROM python:3.12-alpine

LABEL maintainer="d-rag"
LABEL description="Aggregiert Projektdateien in eine einzelne Markdown-Datei"
LABEL version="1.0.0"

# Keine externen Dependencies nötig - nur Python stdlib
WORKDIR /app

# Skript kopieren
COPY projekt_aggregator.py /app/

# Optionaler Mount-Point für Konfigurationsdateien (z.B. Beschreibungen)
# Verwendung: -v /host/config:/config
RUN mkdir -p /config

# Arbeitsverzeichnis für gemountete Projekte
WORKDIR /project

# Standardmäßig das Skript ausführen
ENTRYPOINT ["python", "/app/projekt_aggregator.py"]

# Default: Hilfe anzeigen wenn keine Argumente
CMD ["--help"]
