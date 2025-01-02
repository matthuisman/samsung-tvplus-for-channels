FROM python:3.12-slim

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 80/tcp

ENV IS_DOCKER=1

CMD [ "python", "-u", "./app.py" ]
