FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# waitress-serve en vez del dev server de Flask (run.py hace app.run(debug=...),
# no apto para producción — Flask mismo lo advierte en cada arranque).
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "run:app"]
