# Default MariaDB pipeline acceptance

`run.sh` exercises the versioned default `PIPELINE_MODE=mariadb` instead of replacing it with the
optional synchronous gRPC evaluation pipeline. It builds the standard Compose services on a
fresh database volume and proves:

- `vor-1` may insert/update requests but cannot delete them;
- `vor-2` may consume through `get_next_request()` but cannot insert requests;
- a request submitted over secured OPC UA traverses Interface gRPC, MariaDB, the VoR-CPC
  consumer and the typed CPC gRPC/mTLS service while legacy port 5000 stays closed; and
- the deterministic Modbus register changes from 42 to 9, is read back as 9 and the queue is
  empty afterwards.

The test is a Docker-Compose integration result. The legacy unauthenticated Flask bridge remains
available only through an explicit compatibility opt-in; it is not started by the tested default.
The result is not evidence for PikeOS/ELinOS partition isolation.
