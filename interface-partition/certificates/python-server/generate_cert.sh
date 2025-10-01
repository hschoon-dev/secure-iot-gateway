#! /bin/bash
openssl genrsa -out server_key.pem 2048
openssl req -x509 -days 365 -new -out server_cert.pem -key server_key.pem -config ssl.conf
openssl x509 -in server_cert.pem -out server_cert.der -outform DER