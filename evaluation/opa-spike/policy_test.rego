package siot.authz_test

import rego.v1

import data.siot.authz.allow
import data.siot.authz.deny_reason

pump_input(value) := {
    "user": {"id": "alice", "roles": ["PlantOperator"]},
    "action": "flow rate adjustment",
    "parameter": "Pump_B_Power",
    "value": value,
    "limits": {"pump_b_power_max_kw": 16.0},
}

test_operator_below_mapping_limit if {
    allow with input as pump_input(15.0)
}

test_admin_below_mapping_limit if {
    allow with input as object.union(
        pump_input(15.0),
        {"user": {"id": "admin", "roles": ["Admin"]}},
    )
}

test_operator_at_mapping_limit_is_denied if {
    not allow with input as pump_input(16.0)
}

test_operator_above_mapping_limit_is_denied if {
    not allow with input as pump_input(16.1)
}

test_denial_explains_mapping_limit if {
    reasons := deny_reason with input as pump_input(16.0)
    count(reasons) == 1
}

test_non_admin_cannot_manage_users if {
    not allow with input as {
        "user": {"id": "bob", "roles": ["PlantOperator"]},
        "action": "manage_users",
        "parameter": "UserManagement",
        "value": 0,
        "limits": {"pump_b_power_max_kw": 16.0},
    }
}

test_admin_can_manage_users if {
    allow with input as {
        "user": {"id": "admin", "roles": ["Admin"]},
        "action": "manage_users",
        "parameter": "UserManagement",
        "value": 0,
        "limits": {"pump_b_power_max_kw": 16.0},
    }
}
