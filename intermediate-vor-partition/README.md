# Intermediate VoR Partition

This repository contains the implementation of the Intermediate VoR Partition, which handles message queue communication using POSIX IPC. The main script initializes and manages the message queue, receives messages, and logs the received messages.

## Contents
- `main.py`: The main script that initializes the message queue handler and starts receiving messages.

## Requirements
- Python 3.8+
- posix_ipc library for POSIX IPC

## Script Details
### Libraries Used
- `posix_ipc`: Provides access to POSIX inter-process communication primitives such as message queues, semaphores, and shared memory.
- `logging`: Standard Python library for logging messages.
- `time`: Standard Python library for time-related functions.

### Functions and Classes
`RequestMessageHandler`
This class handles the message queue operations.

`__init__(self, message_queue_name: str)`: Initializes the RequestMessageHandler with the specified message queue name and attaches to the message queue.

- `message_queue_name`: The name of the message queue to attach to.

`_attach_message_queue(self)`: Attaches to the message queue with the specified name.
- Returns: The attached message queue object or None if an error occurs.

`receive_message(self, interval: float)`: Receives messages from the message queue at the specified interval.

- `interval`: The interval (in seconds) between message checks.

`_rcv_notification(self)`: Callback function for receiving message queue notifications. Logs the received message and re-registers for notifications.

`main()`
The main function that initializes the `RequestMessageHandler` and starts receiving messages.
#### Explanation
- Initialization: The script initializes the logging configuration and defines the RequestMessageHandler class.
- Message Queue Attachment: The RequestMessageHandler class attaches to the specified message queue and logs the status.
- Message Reception: The receive_message method sets up a notification callback for receiving messages and enters an infinite loop.