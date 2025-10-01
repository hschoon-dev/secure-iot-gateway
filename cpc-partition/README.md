# CPC Partition

This folder contains the implementation of a client that interfaces with both OPC UA and Modbus TCP servers. It retrieves data from these servers, processes it, and writes it to Shared Memory. The client uses secure communication with certificates and enables shared memory for inter-process communication (IPC).

## Contents

### `main.py`

The `main.py` script initializes and starts the OPC UA and Modbus TCP clients, schedules periodic read tasks, and handles shared memory operations. It uses multi-threading to run both clients concurrently.

Key functions:
- `opcua_service()`: Initializes OPC UA shared memory and semaphores, creates clients, and reads data from OPC UA servers.
- `modbus_tcp_service()`: Initializes Modbus TCP shared memory and semaphores, creates clients, and reads data from Modbus TCP servers.
- `main()`: Creates and manages threads for OPC UA and Modbus TCP services.

### Libraries

#### `modbus_tcp_client`

This library contains the `ModbusClientManager` class, which manages Modbus TCP clients. It handles communication with Modbus TCP servers and writes data to shared memory.

Key classes and methods:
- `ModbusClientManager`: Manages Modbus TCP clients.
  - `create_clients()`: Creates instances of `ModbusTCPClient` from XML configuration.
  - `start_clients()`: Initializes the Modbus TCP clients.
  - `periodic_read(interval, shm_list, semaphore_list)`: Periodically reads data from Modbus TCP servers and updates shared memory with semaphore protection.
  - `load_endpoints_from_xml()`: Parses the XML configuration file for Modbus TCP endpoints.
- `ModbusTCPClient`: Represents a Modbus TCP client.
  - `retry_connection()`: Attempts to reconnect to the Modbus server if connection is lost.
  - `fc01_read_coil_status()`: Reads coil status (Function Code 01).
  - `fc02_read_discrete_inputs()`: Reads discrete inputs (Function Code 02).
  - `fc03_read_holding_registers()`: Reads holding registers (Function Code 03).

#### `opcua_client`

This library contains the `OpcUaClientManager` class, which manages OPC UA clients. It handles secure communication with OPC UA servers using advanced encryption.

Key classes and methods:
- `OpcUaClientManager`: Manages OPC UA clients.
  - `parse_clients()`: Parses client configurations from XML.
  - `start_clients()`: Establishes secure connections to OPC UA servers.
  - `periodic_read(interval, shm_list, semaphore_list)`: Periodically reads data from OPC UA servers and updates shared memory with semaphore protection.
  - `stop_clients()`: Properly closes client connections.
- `OpcUaClient`: Represents an OPC UA client connection.
  - `connect()`: Establishes a secure connection to the OPC UA server.
  - `disconnect()`: Closes the connection to the OPC UA server.
  - `read_value(node_id)`: Reads a value from a specific node.

### `config` Folder

The `config` folder contains XML and XSD files for configuring the OPC UA and Modbus TCP endpoints.

- `opcua-endpoints.xml`: Configuration file for OPC UA endpoints.
- `opcua-endpoints.xsd`: Schema file for OPC UA endpoints.
- `modbustcp-endpoints_ecotec.xml`: Configuration file for Modbus TCP endpoints for Ecotec devices.
- `modbustcp-endpoints.xsd`: Schema file for Modbus TCP endpoints.

### `Dockerfile`

The `Dockerfile` sets up the environment for running the CPC Partition client.

## Prerequisites

Before running the project, ensure you have the following:

- **Python 3.8+**
- **Docker** (if using the Dockerfile)
- OPC UA and Modbus servers set up and accessible
- Certificates for secure communication
- [`posix-ipc`](https://github.com/osvenskan/posix_ipc) package for semaphore handling

## Configuration

### Shared Memory and Semaphores

The application uses named shared memory segments and semaphores for inter-process communication:

```python
# For OPC UA
opcua_shm_name = 'opcua_shm'
opcua_semaphore_name = 'opcua_semaphore'

# For Modbus TCP
modbus_shm_name = 'modbus_shm'
modbus_semaphore_name = 'modbus_semaphore'
```

### XML Configuration

Configure endpoints in the respective XML files:

- `config/opcua-endpoints.xml`: Define OPC UA servers and nodes to monitor
- `config/modbustcp-endpoints_ecotec.xml`: Define Modbus TCP servers and registers/coils to read

### Error Handling

The application includes reconnection logic for Modbus TCP clients with a 30-second retry interval and monitors shared memory usage to prevent overflow.