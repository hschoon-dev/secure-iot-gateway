## Setup of the MariaDB database
The database is used for the Request-Transport from the VoR-1-partition to the VoR-2-partition. It is hosted on a RPi 4B (siot@192.168.178.117).

### Configuration
```terminal
 > SHOW DATABASES;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| mysql              |
| performance_schema |
| secure_iot_gateway |
+--------------------+
```

```terminal
 > SELECT user, host FROM mysql.user;
+------------------+-----------+
| user             | host      |
+------------------+-----------+
| root             | localhost |
| vor-1            | %         |
| vor-2            | %         |
+------------------+-----------+
```
Default passwords for the users are: VoR-X-Password with 'X' as the partition number.

### User-Management
```terminal
-- Remove old user
DROP USER 'vor-X'@'%';

-- Create new users with remote access
CREATE USER 'vor-X'@'%' IDENTIFIED BY 'NewPassword';

-- Grant privileges to the database
GRANT ALL PRIVILEGES ON secure_iot_gateway.* TO 'vor-X'@'%';

FLUSH PRIVILEGES;
```