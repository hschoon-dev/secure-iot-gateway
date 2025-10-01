# Developer Guide: Secure IoT Gateway

This guide provides steps and recommendations for developers working with the Secure IoT Gateway, tailored for different lab setups and industrial demonstrators. Follow the instructions for your environment to ensure correct integration and configuration.

---

## RWTH/IAT Lab Setup

1. **Update Endpoints in XML Configuration**
   - Edit the XML files for OPC UA and MODBUS/TCP servers in:
     - `secure-iot-gateway/cpc-partition/config/`
   - Ensure endpoints match the network and equipment in your IAT-Lab.

2. **Update RBAC Configuration**
   - Modify the roles and actions in:
     - `secure-iot-gateway/interface-partition/authorization_handler/rbac_test_with_impacts.csv`
   - Actions should correspond to VoR-impacts relevant to your use case.

3. **Develop VoR Functionalities**
   - Implement and test new VoR features in:
     - `secure-iot-gateway/intermediate-vor-partition/`
     - `secure-iot-gateway/intermediate-vor-partition-cpc/`
   - Coordinate with the team to ensure correct mapping and propagation logic.

---

## OMAG Lab Setup

1. **Update Endpoints in XML Configuration**
   - Edit the XML files for OPC UA and MODBUS/TCP servers in:
     - `secure-iot-gateway/cpc-partition/config/`
   - Set endpoints according to your OMAG demonstrator network.

2. **Update OPC UA Certificates**
   - Add trusted client certificates (`.der` format) to:
     - `secure-iot-gateway/interface-partition/certificates/trusted/certs/`
   - Register new clients in the OPC UA server setup:
     - Edit `secure-iot-gateway/interface-partition/interface_setup/interface_setup.py` (see line 140+)
     - Use the `add_user` method to add new client certificates.

3. **Central M+O Services Development**
   - Program your own Central M+O services as needed.
   - The OPC UA server certificate for client authentication is located at:
     - `secure-iot-gateway/interface-partition/certificates/python-server/server_cert.der`

---

## General Recommendations

- **Configuration Management**: Always document changes to configuration files and certificates.
- **Testing**: After updates, test connectivity and authorization flows using UAExpert or your preferred OPC UA client.

---

For further details, refer to the main `README.md` and contact the maintainers listed there.
