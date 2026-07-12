FROM mariadb@sha256:be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350

COPY 01_init.sh /docker-entrypoint-initdb.d/01_init.sh
RUN chmod 0755 /docker-entrypoint-initdb.d/01_init.sh
