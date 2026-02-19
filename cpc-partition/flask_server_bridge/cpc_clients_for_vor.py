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



from defusedxml import ElementTree as ET
import xmlschema
from pathlib import Path
import asyncio
import logging
from asyncua import ua

from opcua_client import OpcUaClient

_logger = logging.getLogger(__name__)

class OnDemandOpcUaRegistry:
    def __init__(self, xml_config_path: str | Path, xsd_path: str | Path):
        self.xml_config_path = str(xml_config_path)
        self.xsd_path = str(xsd_path)
        self.clients: list[OpcUaClient] = []
        # key: "DisplayName" und zusätzlich "NamespaceAlias:DisplayName"
        self.node_lookup: dict[str, tuple[OpcUaClient, ua.NodeId]] = {}
        self._build()

    def _build(self) -> None:
        schema = xmlschema.XMLSchema(self.xsd_path)
        if not schema.is_valid(self.xml_config_path):
            _logger.error("OPC UA XML does not conform to XSD: %s", self.xml_config_path)

        tree = ET.parse(self.xml_config_path)
        root = tree.getroot()

        for server in root.findall("server"):
            server_app_uri = server.findtext("server_app_uri")
            client_app_uri = server.findtext("client_app_uri")
            alias = server.findtext("alias")

            sec = server.find("security")
            security_settings = {
                "policy": sec.findtext("policy"),
                "mode": sec.findtext("mode"),
                "client_certificate": sec.findtext("client_certificate"),
                "client_private_key": sec.findtext("client_private_key"),
                "server_certificate": sec.findtext("server_certificate"),
                "username": sec.findtext("username"),
                "password": sec.findtext("password"),
            }

            nodes_cfg = []
            for node in server.findall("nodes/node"):
                display_name = (node.findtext("DisplayName") or "").strip()
                ns_alias = (node.findtext("NamespaceAlias") or "").strip()
                id_type = (node.findtext("IdentifierType") or "").strip()
                ns_idx = int(node.findtext("NamespaceIndex"))
                ident = (node.findtext("Identifier") or "").strip()

                if id_type == "String":
                    node_id = ua.NodeId.from_string(f"ns={ns_idx};s={ident}")
                elif id_type == "Numeric":
                    node_id = ua.NodeId(int(ident), ns_idx)
                else:
                    raise NotImplementedError(f"IdentifierType {id_type} not supported")

                nodes_cfg.append({"node_id": node_id, "display_name": display_name, "namespace_alias": ns_alias})

            c = OpcUaClient(server_app_uri, client_app_uri, alias, security_settings, nodes=[])
            self.clients.append(c)

            # lookup befüllen: DisplayName und NamespaceAlias:DisplayName
            for n in nodes_cfg:
                dn = n["display_name"]
                na = n["namespace_alias"]
                node_id = n["node_id"]
                if dn:
                    self.node_lookup[dn] = (c, node_id)
                if na and dn:
                    self.node_lookup[f"{na}:{dn}"] = (c, node_id)

        _logger.warning("OnDemandOpcUaRegistry built: %d clients, %d nodes",
                        len(self.clients), len(self.node_lookup))

    async def fetch(self, var_names: list[str], timeout_s: float = 3.0) -> dict[str, object]:
        """
        Liest Werte on-demand.
        Rückgabe-Keys = genau die angefragten Namen (damit euer Fill-Code passt).
        Unbekannt => kein Eintrag (caller kann dann N/A einsetzen)
        """
        # gruppieren nach Client
        by_client: dict[OpcUaClient, list[tuple[str, ua.NodeId]]] = {}
        for req_name in var_names:
            hit = self.node_lookup.get(req_name)
            if hit is None:
                continue
            client, node_id = hit
            by_client.setdefault(client, []).append((req_name, node_id))

        results: dict[str, object] = {}

        async def _read_for_client(client: OpcUaClient, items: list[tuple[str, ua.NodeId]]):
            await client.connect()
            try:
                if not client.connected:
                    _logger.error("OPC UA client not connected: %s", client.server_app_uri)
                    return
                for req_name, node_id in items:
                    _bn, value, _vt = await client.read_value(node_id)
                    results[req_name] = value
            finally:
                # für dev/test ok; später ggf. persistent connecten
                await client.disconnect()

        tasks = [asyncio.wait_for(_read_for_client(c, items), timeout=timeout_s)
                 for c, items in by_client.items()]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results


async def vor_5_placeholder():
    await asyncio.sleep(1)
    return f"Placeholder 'VoR_5 call for CPC state' result"

async def placeholder_opcua_client():
    # BUG: Not completed
    # It has to be a secured conn because its the secured brownflied server :(
    # and what if the ressources are distributed over several servers? Modbus and OPC UA?
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

async def vor_6_placeholder():
    await asyncio.sleep(1)
    return f"Placeholder 'VoR_6 call for implement CPC change' result"
