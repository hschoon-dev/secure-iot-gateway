# Brownfield OPC UA Server

This folder contains the implementation of OPC UA servers for brownfield devices. The main script to run the servers is `main.py`.

## Contents

### `main.py`

This script starts the secured OPC UA server. The `NoSecurity` implementation is retained solely for isolated compatibility tests and is disabled by default.

The script defines two functions:
- `run_secured_server()`: Runs the secured OPC UA server using `asyncio.run()`.

The `NoSecurity` server can be started only with both `SIOT_DEPLOYMENT_MODE=test` and `ENABLE_INSECURE_OPCUA_TEST_SERVER=true`. Any other mode rejects that opt-in. The `__main__` block handles `KeyboardInterrupt` to gracefully shut down all started processes.

### Libraries

#### `opcua_unsecured_server`

This library contains the implementation of the unsecured OPC UA server. The main function `start_unsecured_server` initializes and starts the server.

#### `opcua_secured_server`

This library contains the implementation of the secured OPC UA server. The main function `start_secured_server` initializes and starts the server with security configurations.

### Dockerfile

The `Dockerfile` in this folder is used to create a Docker image for the brownfield OPC UA server. It typically includes instructions to:
- Set up the base image
- Install necessary dependencies
- Copy the server code into the image
- Define the entry point to run the servers

## Usage

To run the secured OPC UA server, execute `main.py` with the normal runtime-secret configuration:

```sh
python main.py
```

Do not enable the `NoSecurity` server outside an isolated test environment.
