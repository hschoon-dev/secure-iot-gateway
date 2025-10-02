"""
------------------------------------------------------------
 Modul:    cpc-partition/cpc_clients_for_vor.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains client implementations for the
    communication with the CPC in the context of the VoR 
    framework.
    It includes functions to interact with both OPC UA
    and Modbus servers, allowing for reading and writing
    of variables as required by the VoR processes.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development. Not all functions are fully implemented.
------------------------------------------------------------
"""

from asyncua import Client
from asyncua import ua
import asyncio

from pyModbusTCP.client import ModbusClient
from pyModbusTCP.utils import test_bit, set_bit

import logging
from time import sleep

_logger = logging.getLogger(__name__)

# tbc

def vor_5_placeholder():
    sleep(1)
    return f"Placeholder 'VoR_5 call for CPC state' result"

def placeholder_opcua_client():
    # BUG: Not completed
    # It has to be a secured conn because its the secured brownflied server :(
    return

async def read_list_of_vars_from_opcua(client: Client, var_names: list[str]) -> dict[str, any]: # BUG: Not completed
    results = {}
    try:
        async with client:
            for var_name in var_names:
                node = client.get_node(var_name)
                val = await node.read_value()
                results[var_name] = val
    except Exception as e:
        _logger.error(f"Error reading from OPC UA: {e}")
    return results

async def read_list_of_vars_from_modbus(client: ModbusClient, var_names, endpoints): # BUG: Not completed
    results = {}
    try:
        if not client.is_open():
            if not client.open():
                _logger.error(f"Unable to connect to Modbus server at {client.host}:{client.port}")
                return results
        for var_name in var_names:
            endpoint = endpoints.get(var_name)
            if endpoint:
                fc = endpoint['function_code']
                if fc == 1:
                    val = client.read_coils(endpoint['address'], endpoint['quantity'])
                elif fc == 2:
                    val = client.read_discrete_inputs(endpoint['address'], endpoint['quantity'])
                elif fc == 3:
                    val = client.read_holding_registers(endpoint['address'], endpoint['quantity'])
                elif fc == 4:
                    val = client.read_input_registers(endpoint['address'], endpoint['quantity'])
                else:
                    _logger.error(f"Unsupported function code {fc} for {var_name}")
                    continue
                results[var_name] = val[0] if val else None
            else:
                _logger.error(f"No endpoint configuration for {var_name}")
    except Exception as e:
        _logger.error(f"Error reading from Modbus: {e}")
    return results

def vor_6_placeholder():
    sleep(1)
    return f"Placeholder 'VoR_6 call for implement CPC change' result"
