# Default MariaDB pipeline acceptance

`run.sh` exercises the versioned default `PIPELINE_MODE=mariadb` instead of replacing it with the
optional synchronous gRPC evaluation pipeline. It builds the standard Compose services on a
fresh database volume and proves:

- `vor-1` may insert/update requests but cannot delete them;
- `vor-2` may consume through `get_next_request()` but cannot insert requests;
- a request submitted over secured OPC UA traverses Interface gRPC, MariaDB, the VoR-CPC
  consumer and the CPC bridge; and
- the deterministic Modbus register changes from 42 to 9, is read back as 9 and the queue is
  empty afterwards.

The test is a Docker-Compose integration result. It does not turn the temporary HTTP CPC bridge
into a protected target-deployment channel and is not evidence for PikeOS/ELinOS partition
isolation.
