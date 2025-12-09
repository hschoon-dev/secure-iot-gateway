# Secure IoT Gateway and Certificate Authorities

Here we describe the implementation of an self-signed CA. This is necessary for the gRPC communication with mTLS.
Overview of gRPC services of the SIoT-Gateway and necessary certificates/keys:
```bash
gRPC:
secure-iot-gateway
├─ CPC-Partition (grpc-Client for the psM+O- AND the Interface-Partition)
│  ├─ Certificates: cpc-client.crt, ca.crt 
│  └─ Private keys: cpc-client.key
│
├─ psM+O-Partition (grpc-Server)
│  ├─ Certificates: psmo-server.crt, ca.crt
│  └─ Private keys: psmo-server.key
│
├─ Interface-Partition (grpc-Server for the CPC-partition), (grpc-Client for the Intermed.-VoR-Partition)
│  ├─ Certificates: interface-server.crt, interface-client.crt, ca.crt
│  └─ Private keys: interface-server.key, interface-client.key
│
├─ Interm.-VoR-Partition (grpc-Server for the Interface-partition)
│  ├─ Certificates: intermediate-vor-server.crt ca.crt
│  └─ Private keys: intermediate-vor-server.key
│
├─ Certificate-Authority
│  ├─ Certificates: ca.crt
│  └─ Private keys: ca.key
└─ ...
# the CA-certificate of the corresponding gRPC-server/-client is needed 
# (in this example the CA is the same for all)

OPCUA+ModbusTCP:
secure-iot-gateway
├─ CPC-Partition (OPCUA-Client for the CPC-Domain)
│  ├─ Certificates: cpc-opcua-client.crt, {cpc-endpoint-1.crt, cpc-endpoint-2.crt, ...}, pot. ca.crt
│  └─ Private keys: cpc-opcua-client.key
│
├─ Interface-Partition (OPCUA-Server for the Central-M+O-Domain)
│  ├─ Certificates: interface-opcua-server.crt, {central-mo-client-1.crt, central-mo-client-2.crt, ...}, pot. ca.crt
│  └─ Private keys: interface-opcua-server.key
└─ ...
```

____

Example ssl.cnf for a gRPC client or server:
```bash
[ req ]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = v3_req

[ dn ]
CN = grpc-server

[ v3_req ]
subjectAltName = @alt_names
extendedKeyUsage = serverAuth
keyUsage = digitalSignature, keyEncipherment

[ alt_names ]
DNS.1 = grpc-server
DNS.2 = intermediate-vor-partition
DNS.3 = localhost
IP.1  = 127.0.0.1
IP.2 = 172.20.128.9 # optional; avoid if IP is ephemeral
```
____

Create CA and the CA-signed Certificates:
```bash
# 1) Root CA
openssl genrsa -out certs/ca/ca.key 4096
openssl req -x509 -new -nodes -key certs/ca/ca.key -sha256 -days 3650 \
  -subj "/CN=demo-root-ca" -out certs/ca/ca.crt

# 2) Server cert (SAN includes grpc-server)
openssl genrsa -out certs/server/server.key 4096
cat > certs/server/server.cnf <<EOF
[req]
distinguished_name=req
req_extensions=req_ext
prompt=no
[req_ext]
subjectAltName=DNS:grpc-server,DNS:localhost,IP:127.0.0.1
[dn]
CN=grpc-server
EOF
openssl req -new -key certs/server/server.key -out certs/server/server.csr \
  -subj "/CN=grpc-server" -config certs/server/server.cnf
openssl x509 -req -in certs/server/server.csr -CA certs/ca/ca.crt -CAkey certs/ca/ca.key -CAcreateserial \
  -out certs/server/server.crt -days 825 -sha256 -extfile certs/server/server.cnf -extensions req_ext

# 3) Client cert
openssl genrsa -out certs/client/client.key 4096
openssl req -new -key certs/client/client.key -out certs/client/client.csr -subj "/CN=demo-client"
openssl x509 -req -in certs/client/client.csr -CA certs/ca/ca.crt -CAkey certs/ca/ca.key -CAcreateserial \
  -out certs/client/client.crt -days 825 -sha256
```

____

Example bash commands for setting up the .crt and .key:
```bash
# server key
openssl genrsa -out server.key 4096

# CSR using the config (pulls CN + SANs from it)
openssl req -new -key server.key -out server.csr -config ssl.conf

# Sign with your CA, making sure the same ext section is applied
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
-out server.crt -days 825 -sha256 -extensions v3_req -extfile ssl.conf
```