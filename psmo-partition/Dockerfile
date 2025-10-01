FROM python:3

LABEL maintainer="Heiko Schoon, Hochschule Emden/Leer, Fachbereich Technik, <heiko.schoon@hs-emden-leer.de>"

WORKDIR /app 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Berlin

COPY . .

CMD [ "python3", "-u", "./main.py" ]

