# Brownfield OPC UA Server

This folder contains the implementation of OPC UA servers for brownfield devices. The main script to run the servers is `run_test_servers.py`.

## Contents

### `run_test_servers.py`

This script is responsible for starting both secured and unsecured OPC UA servers using multiprocessing. It imports the following functions:
- `start_unsecured_server` from `opcua_unsecured_server`
- `start_secured_server` from `opcua_secured_server`

The script defines two functions:
- `run_unsecured_server()`: Runs the unsecured OPC UA server using `asyncio.run()`.
- `run_secured_server()`: Runs the secured OPC UA server using `asyncio.run()`.

In the `__main__` block, the script creates two processes to run the unsecured and secured servers concurrently. It handles `KeyboardInterrupt` to gracefully shut down the servers.

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

To run the OPC UA servers, execute the `run_test_servers.py` script:

```sh
python run_test_servers.py
```