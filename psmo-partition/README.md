# PSMO Partition

This folder contains the implementation of the PSMO (Process and State Monitoring and Optimization) partition. It includes scripts for handling shared memory and semaphores, as well as a main script to start the OPC UA and Modbus TCP threads. The Dockerfile is used to create a Docker image for running the PSMO partition.

## Contents

### `psmo_shm_handler.py`

This script contains the implementation of the `OPCUA_Thread` and `ModbusTCP_Thread` classes, which handle reading from shared memory and managing semaphores for OPC UA and Modbus TCP communication.

#### Key Classes:
- `OPCUA_Thread`: Handles reading from OPC UA shared memory and managing the associated semaphore.
- `ModbusTCP_Thread`: Handles reading from Modbus TCP shared memory and managing the associated semaphore.

### `main.py`

The main script initializes and starts the OPC UA and Modbus TCP threads, and processes the data retrieved from the shared memory.

### `Dockerfile`

The Dockerfile sets up the environment for running the PSMO partition. It installs the necessary dependencies and copies the required files into the Docker image.

#### Key Steps:
- Install Python and required libraries.
- Copy the project files into the Docker image.
- Set the entry point to run `main.py`.

## Usage

Only run the Docker container within the given container network of the SIoT Gateway implementation (`docker-compose.yaml`)

## License

This project is licensed under the MIT License. See the LICENSE file for details.