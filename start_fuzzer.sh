#!/bin/bash

# Possible request types:
# read_request, browse_request, browse_next_request, create_subscription_request, add_nodes_request, history_read_request
env FUZZER_REQUEST_TYPE=read_request \
    FUZZER_PORT=26000 \
    FUZZER_LOGS=./opcua_network_fuzzer/logs \
    FUZZER_RESULTS=./opcua_network_fuzzer/results \
    docker compose -f docker-compose-fuzzer.yaml up --build -d