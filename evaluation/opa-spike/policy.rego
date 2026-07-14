package siot.authz

# Rego v1 (parst auf aktuellem OPA ohne --v0-compatible).
import rego.v1

default allow := false

has_role(role) if {
    some r in input.user.roles
    r == role
}

can_operate if {
    has_role("PlantOperator")
}

can_operate if {
    has_role("Admin")
}

allow if {
    input.action == "flow rate adjustment"
    input.parameter == "Pump_B_Power"
    can_operate
    input.value < input.limits.pump_b_power_max_kw
}

allow if {
    input.action == "manage_users"
    has_role("Admin")
}

deny_reason contains msg if {
    input.action == "manage_users"
    not has_role("Admin")
    msg := "manage_users requires Admin role"
}

deny_reason contains msg if {
    input.action == "flow rate adjustment"
    input.parameter == "Pump_B_Power"
    can_operate
    input.value >= input.limits.pump_b_power_max_kw
    msg := sprintf(
        "Pump_B_Power %.2f must be below %.2f kW",
        [input.value, input.limits.pump_b_power_max_kw],
    )
}
