package system.authz_test

import rego.v1

import data.system.authz.allow

test_interface_may_evaluate_only_gateway_decision if {
    allow with input as {
        "identity": "CN=grpc-client-interface",
        "method": "POST",
        "path": ["v1", "data", "siot", "authz", "allow"],
    }
}

test_other_gateway_identity_is_denied if {
    not allow with input as {
        "identity": "CN=grpc-client-cpc",
        "method": "POST",
        "path": ["v1", "data", "siot", "authz", "allow"],
    }
}

test_interface_cannot_access_management_api if {
    not allow with input as {
        "identity": "CN=grpc-client-interface",
        "method": "GET",
        "path": ["v1", "policies"],
    }
}
