"""from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class Issuer:
    def __init__(self, issuer_id, credentials, valid_from, valid_until, characteristics=None):
        self.issuer_id = issuer_id
        self.credentials = credentials       #tokens, certificates, keys, etc.
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.characteristics = characteristics      #optional, IP adress, container instance, model identifier, etc.

    def is_valid(self):     #check the validity of Issuer
        current_time = datetime.now()
        return self.valid_from <= current_time <= self.valid_until

# Record Request Issuer 
class IssuerRegistry:
    def __init__(self):
        self.issuers = {}

    def add_issuer(self, issuer: Issuer):
        self.issuers[issuer.issuer_id] = issuer

    def validate_issuer(self, issuer_id, credentials):
        issuer = self.issuers.get(issuer_id)

        if not issuer:      #check existence
            _logger.warning(f"Validation failed: Issuer {issuer_id} not found")
            return False
        if issuer.credentials != credentials:       #check credentials
            _logger.warning(f"Validation failed: Invalid credentials for {issuer_id}")
            return False
        if not issuer.is_valid():       #check validity
            _logger.warning(f"Validation failed: Issuer {issuer_id} is expired or not yet valid")
            return False

        return True"""