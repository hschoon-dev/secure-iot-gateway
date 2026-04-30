from logging import getLogger
import uuid

# This will continually leak memory as the logger creates a logger object
# for each getLogger call and stores it in a dict for later usage
while True:
    _logger = getLogger(str(uuid.uuid4()))
    # Uncomment to prevent memory growth
    # _logger.manager._clear_cache()