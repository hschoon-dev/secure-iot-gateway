# Isolated rotation test

`run_isolated.sh` copies the gateway into a temporary directory and performs
all key generation and rotation there. It never modifies active runtime
secrets.

The test uses the real certificate generator, externalization script, rotation
script, and Python gRPC TLS stack. It proves:

1. the old client works with the old CA;
2. the CA fingerprint changes during rotation;
3. the newly issued client works with the new server and CA;
4. the old client is rejected by the new server.

The temporary containers, network, repository copy, and key material are
removed on exit.
