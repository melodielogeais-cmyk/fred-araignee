# Araignée en continu + tableau de bord (port 4010). Aucune dépendance externe.
FROM python:3.12-slim
WORKDIR /app
COPY araignee ./araignee
COPY config.json index.html ./
RUN mkdir -p data
ENV PYTHONUNBUFFERED=1 PORT=4010
EXPOSE 4010
CMD ["python", "-m", "araignee", "live"]
