package system.authz

import rego.v1

# OPA's management and query APIs are fail-closed. The production gateway
# interface may only evaluate the single decision document it consumes.
default allow := false

allow if {
    input.identity == "CN=grpc-client-interface"
    input.method == "POST"
    input.path == ["v1", "data", "siot", "authz", "allow"]
}
