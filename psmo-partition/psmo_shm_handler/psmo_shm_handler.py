from threading import Thread, Event
import time
import json
#import asyncio
from multiprocessing import shared_memory
import logging
from queue import Queue

import posix_ipc
import hashlib


_logger = logging.getLogger(__name__)

class OPCUA_Thread(Thread):
    def __init__(self, semaphore_name: str, shared_memory_name: str, message_queue: Queue = None):
        self._sem_name = semaphore_name
        self._shm_name = shared_memory_name
        self._queue = message_queue
        Thread.__init__(self)
        self._stop_event = Event()

    def run(self):
        try:
            # await queue.async_put(1)
            semaphore = posix_ipc.Semaphore(self._sem_name)
            shm = shared_memory.SharedMemory(name=self._shm_name)
            shm_size = shm.size
        except FileNotFoundError:
            _logger.error(f"Shared memory {self._shm_name} not found.")
            return
        except Exception as e:
            _logger.error(f"Error initializing shared memory: {e}")
            semaphore.close()
            return
        
        response = ""

        while not self._stop_event.is_set():
            try:
                # Read the content from shared memory
                semaphore.acquire()
                opcua_values_json = bytes(shm.buf[:]).decode('utf-8').rstrip('\x00')
                if opcua_values_json:

                    while opcua_values_json == response:
                        semaphore.release()
                        time.sleep(.01)
                        semaphore.acquire()
                        opcua_values_json = bytes(shm.buf[:]).decode('utf-8').rstrip('\x00')
                        #_logger.error(f"Wait for new values...")

                    opcua_values = json.loads(opcua_values_json)
                    
                    if self._queue is not None:
                        try:
                            self._queue.put(opcua_values)
                        except Exception as e:
                            _logger.error(f"Error writing to OPC UA message queue: {e}")
                    else:
                        _logger.info(f"Shared Memory Content of {self._shm_name}: {json.dumps(opcua_values, indent=4)}")

                    response = hashlib.md5(opcua_values_json.encode()).hexdigest()
                    shm.buf[:shm_size] = b'\x00' * shm_size  # Clear the shared memory buffer
                    shm.buf[:len(response)] = response.encode('utf-8')
                semaphore.release()
            except Exception as e:
                _logger.error(f"Error reading shared memory: {e}")
        

    def stop(self):
        self._stop_event.set()

class ModbusTCP_Thread(Thread):
    def __init__(self, semaphore_name: str, shared_memory_name: str, message_queue: Queue = None):
        self._sem_name = semaphore_name
        self._shm_name = shared_memory_name
        self._queue = message_queue
        Thread.__init__(self)
        self._stop_event = Event()

    def run(self):
        try:
            # await queue.async_put(1)
            semaphore = posix_ipc.Semaphore(self._sem_name)
            shm = shared_memory.SharedMemory(name=self._shm_name)
            shm_size = shm.size
        except FileNotFoundError:
            _logger.error(f"Shared memory {self._shm_name} not found.")
            return
        except Exception as e:
            _logger.error(f"Error initializing shared memory: {e}")
            semaphore.close()
            return
        
        response = ""

        while not self._stop_event.is_set():
            try:
                # Read the content from shared memory
                semaphore.acquire()
                modbus_values_json = bytes(shm.buf[:]).decode('utf-8').rstrip('\x00')

                if modbus_values_json:

                    while modbus_values_json == response:
                        semaphore.release()
                        time.sleep(.01)
                        semaphore.acquire()
                        modbus_values_json = bytes(shm.buf[:]).decode('utf-8').rstrip('\x00')
                        #_logger.error(f"Wait for new values...")

                    modbus_values = json.loads(modbus_values_json)
                    if self._queue is not None:
                        try:
                            self._queue.put(modbus_values)
                        except Exception as e:
                            _logger.error(f"Error writing to ModbusTCP message queue: {e}")
                    else:
                        _logger.info(f"Shared Memory Content of {self._shm_name}: {json.dumps(modbus_values, indent=4)}")

                    response = hashlib.md5(modbus_values_json.encode()).hexdigest()
                    shm.buf[:shm_size] = b'\x00' * shm_size  # Clear the shared memory buffer
                    shm.buf[:len(response)] = response.encode('utf-8')
                semaphore.release()
            except Exception as e:
                _logger.error(f"Error reading shared memory: {e}")

    def stop(self):
        self._stop_event.set()