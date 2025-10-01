import asyncio
import sys
import logging
import random
from asyncua import ua
from asyncua import Server
from asyncua.crypto.permission_rules import SimpleRoleRuleset

sys.path.insert(0, "..")

_logger = logging.getLogger(__name__)

async def start_unsecured_server():
    server_app_uri = f"python-server-no-security"

    server = Server() 
    await server.init()
    await server.set_application_uri(server_app_uri)
    server.set_endpoint("opc.tcp://0.0.0.0:4841/freeopcua/server/")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity],
                               permission_ruleset=SimpleRoleRuleset())

    variables = []

    for ns in range(1, 4, 1):
        idx = await server.register_namespace(ns)
        myobj = await server.nodes.objects.add_object(idx, f"Object")
        bool_var = await myobj.add_variable(idx, f"PieceProduced", False)
        #test_nodeid = ua.NodeId.from_string(f"ns={idx};s=Temperature")
        #float_var = await myobj.add_variable(test_nodeid, f"Temperature", ua.Float(0.0))
        float_var = await myobj.add_variable(idx, f"Temperature", ua.Float(0.0))
        int_var = await myobj.add_variable(idx, f"ProductionStep", ua.Int32(0))
        string_var = await myobj.add_variable(idx, f"OperationMode", ua.String("Normal Operation"))
        
        await bool_var.set_read_only()
        await float_var.set_read_only()
        await int_var.set_read_only()
        await string_var.set_read_only()
        
        variables.append((bool_var, float_var, int_var, string_var))

    test_nodeid = ua.NodeId.from_string(f"ns={idx};s=TestWithStringNodeId")
    test_var = await myobj.add_variable(test_nodeid, f"TestWithStringNodeId", ua.String("Test"))
    
    _logger.info(f"Overview of all variables: {variables}")
    #_logger.info(f"Overview of all variables on server: {await server.nodes.objects.get_children()}")

    async with server:
        _logger.warning("Server started!")
        while True:
            await asyncio.sleep(1)
            for bool_var, float_var, int_var, string_var in variables:
                await bool_var.write_value((random.choice([True, False])))
                await float_var.write_value(ua.Float(random.uniform(80.0, 100.0)))
                await int_var.write_value(ua.Int32(random.randint(0, 10)))
                await string_var.write_value(ua.String(random.choice(["Normal Operation", "Emergency Stop", "Maintenance"])))

if __name__ == "__main__":
    asyncio.run(start_unsecured_server())

'''import asyncio
import sys
import logging
import random
from asyncua import ua
from asyncua import Server
from asyncua.crypto.permission_rules import SimpleRoleRuleset

sys.path.insert(0, "..")

logging.basicConfig(level=logging.WARNING)
_logger = logging.getLogger(__name__)

async def main():
    server_app_uri = f"python-server-no-security"

    server = Server() 
    await server.init()
    await server.set_application_uri(server_app_uri)
    server.set_endpoint("opc.tcp://0.0.0.0:4841/freeopcua/server/")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity],
                               permission_ruleset=SimpleRoleRuleset())

    variables = []

    for ns in range(4):
        idx = await server.register_namespace(ns)
        myobj = await server.nodes.objects.add_object(idx, f"Object")
        bool_var = await myobj.add_variable(idx, f"PieceProduced", False)
        float_var = await myobj.add_variable(idx, f"Temperature", ua.Float(0.0))
        int_var = await myobj.add_variable(idx, f"ProductionStep", ua.Int32(0))
        string_var = await myobj.add_variable(idx, f"OperationMode", ua.String("Normal Operation"))
        
        await bool_var.set_read_only()
        await float_var.set_read_only()
        await int_var.set_read_only()
        await string_var.set_read_only()
        
        variables.append((bool_var, float_var, int_var, string_var))

    async with server:
        _logger.warning("Server started!")
        while True:
            await asyncio.sleep(1)
            for bool_var, float_var, int_var, string_var in variables:
                await bool_var.write_value((random.choice([True, False])))
                await float_var.write_value(ua.Float(random.uniform(80.0, 100.0)))
                await int_var.write_value(ua.Int32(random.randint(0, 10)))
                await string_var.write_value(ua.String(random.choice(["Normal Operation", "Emergency Stop", "Maintenance"])))

if __name__ == "__main__":
    asyncio.run(main())'''