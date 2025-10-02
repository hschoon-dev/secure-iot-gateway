"""
------------------------------------------------------------
 Modul:    interface-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The main function initializes and runs the Intermediate VoR
    partition of the Secure IoT Gateway. It sets up logging,
    shared memory, semaphores, and message queues for inter-process
    communication with other VoR components. The partition listens
    for incoming requests via a message queue, verifies and maps
    them according to predefined rules, and provides feedback
    to the interface partition. The logging configuration supports
    both console and rotating file logging with adjustable log levels.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module,
      added logging, message queue handling, and controlled shutdown)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import posix_ipc
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import signal
import os
from typing import Any, Optional
import json

from request import Request
from request_verification import RequestVerifier, RuleSet
from mapping_verification import RequestMapper, Mapping_RuleSets
from feedback_system import FeedbackSystem

# Configure logging
#logging.basicConfig(
#    level=logging.WARNING,
#    #format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#)
#_logger = logging.getLogger(__name__)

path = os.path.dirname(os.path.abspath(__file__))
verfication_ruleset_path = os.path.join(path, "config/Request_Verification_Ruleset.xml")
mapping_ruleset_path = os.path.join(path, "config/Mapping_Rulesets.xml")
mapped_rq_db_path = os.path.join(path, "config/mapped_requests.db")
logging_path = os.path.join(path, "logs/app.log")

# Global flag for controlled shutdown
_running = True

def setup_logging(
    log_level=logging.WARNING,
    log_file=logging_path,
    max_bytes=1 * 1024 * 1024,  # 1 MB
    backup_count=3
    ) -> logging.Logger:

    # Common log format
    log_format = (
        "[%(asctime)s] [%(levelname)-8s] "
        "[%(name)s:%(lineno)d] - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Rotating file handler
    print(f"Logging to file: {log_file}")
    file_handler = RotatingFileHandler(
        #log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Root logger config
    logging.basicConfig(
        level=log_level,
        handlers=[console_handler, file_handler],
    )

    return logging.getLogger(__name__)

_logger = setup_logging(logging.INFO)


def signal_handler(sig, frame):
    """Handle termination signals"""
    global _running
    _logger.info("Shutdown signal received, exiting gracefully...")
    _running = False

class RequestMessageHandler:
    def __init__(self, message_queue_name: str, verification_ruleset, mapping_ruleset, feedback_system, db_path) -> None:
        """
        Initialize the RequestMessageHandler with a message queue name.
        """
        self._mq_name: str = message_queue_name
        self._mq: Optional[posix_ipc.MessageQueue] = self._attach_message_queue()
        #self._request_verifier: RequestVerifier = request_verifier

        self._verification_ruleset: RuleSet = verification_ruleset
        self._mapping_ruleset: Mapping_RuleSets = mapping_ruleset
        self._feedback_system: FeedbackSystem = feedback_system
        self._db_path: str = db_path
        #self._request_mapper: RequestMapper = request_mapper

        self._request_verifier = RequestVerifier(self._verification_ruleset, self._feedback_system)
        if self._mapping_ruleset.rulesets is not None:
            self._rq_mapper = RequestMapper(self._mapping_ruleset.rulesets, self._feedback_system, self._db_path)
        else:
            _logger.error("INIT: Mapping ruleset is None")
            self._rq_mapper = None

    def _attach_message_queue(self) -> Optional[posix_ipc.MessageQueue]:
        """
        Attach to the message queue
        
        Returns:
            MessageQueue object if successful, None otherwise
        """
        try:
            mq = posix_ipc.MessageQueue(self._mq_name)
            _logger.debug(f"Message Queue {self._mq_name} attached!")
            return mq
        except Exception as e:
            _logger.error(f"Error attaching message queue {self._mq_name}: {e}")
            return None
        
    def receive_message(self, interval: float) -> None:
        """
        Start receiving messages with notifications
        
        Args:
            interval: Time interval between connection attempts if queue is unavailable
        """
        if self._mq is not None:
            try:
                self._mq.request_notification((self._notification_handler, None))
                _logger.debug("Notification request registered")
            except Exception as e:
                _logger.error(f"Error setting up notification: {e}")
        else:
            _logger.error("Message queue not available")

    def _notification_handler(self, *args: Any) -> None:
        """
        Callback function for message queue notification.
        This gets called when a new message arrives.
        """
        if not _running:
            return
            
        try:
            if self._mq is None:
                _logger.error("Message queue not available in notification handler")
                return

            # Receive the actual message
            message, prio = self._mq.receive()
            try:
                message_str = message.decode('utf-8')
                #_logger.info(f"Request with priority {prio} and payload {message_str} received.")
                # Process the message
                _rq = self.parse_request_message(message)
                _verified_rq = None

                if _rq is not None:
                    _logger.debug(f"Parsed request: {_rq}")
                    # Process the request with the verifier
                    _verified_rq = self.process_request(_rq)
                else:
                    _logger.error("Failed to parse request message")

                if _verified_rq is not None:
                    # Map the verified request
                    self.map_request(_verified_rq)
                else:
                    _logger.error("Failed to map request")
        
            except UnicodeDecodeError:
                _logger.info(f"Request with priority {prio} received (binary data)")
            
            # Register for the next notification only if we're still running
            if _running and self._mq is not None:
                self._mq.request_notification((self._notification_handler, None))
            
        except Exception as e:
            _logger.error(f"Error in notification handler: {e}")
            # Try to re-register only if we're still running
            if _running and self._mq is not None:
                try:
                    self._mq.request_notification((self._notification_handler, None))
                except Exception:
                    pass

    def parse_request_message(self, message: bytes) -> Request | None:
        """
        Parse the request message from the message queue.
        message: The message to parse
        returns:
            Request object if parsing is successful, None otherwise
        """
        try:
            _rq = None
            _logger.debug(f"Processing message: {message}")
            message_str = message.decode('utf-8')
            rq_dict = json.loads(message_str)
            
            # Extract all variables from the decoded JSON as a dictionary
            issuer_id = rq_dict["issuer_id"]
            request_id = rq_dict["request_id"]
            priority = rq_dict["prio"]
            _logger.debug(f"Decoded request: issuer_id={issuer_id}, request_id={request_id}, priority={priority}")

            # NEW:
            issuer_characteristics = []
            issuer_characteristics_dict = rq_dict["issuer_characteristics"]
            for key in sorted(issuer_characteristics_dict.keys()):
                issuer_characteristics.append(issuer_characteristics_dict[key])
            _logger.debug(f"Issuer characteristics: {issuer_characteristics}")


            timestamp = rq_dict["timestamp"]
            _logger.debug(f"Timestamp: {timestamp}")
            parameters = rq_dict["parameters"]
            modification = rq_dict["modification"]
            _logger.debug(f"Parameters: {parameters}, Modification: {modification}")
            
            # Extract descriptions and impacts from their respective dictionaries
            descriptions = []
            impacts = []
            
            description_dict = rq_dict["description"]
            for key in sorted(description_dict.keys()):
                descriptions.append(description_dict[key])
            _logger.debug(f"Descriptions: {descriptions}")
                
            impact = rq_dict["impact"]

            # Create a Request object from the extracted data
            _rq = Request(
                issuer_id=issuer_id,
                issuer_characteristics=issuer_characteristics, # NEW
                request_id=request_id,
                timestamp=timestamp,
                description=description_dict,
                impact=impact,
                parameters=parameters,
                modification=modification,
                priority=priority,
            )
            return _rq
            
        except UnicodeDecodeError:
            _logger.error("Failed to decode message")
            return None
        except json.JSONDecodeError:
            _logger.error("Failed to parse JSON from the message")
            return None
        except Exception as e:
            _logger.error(f"Error processing message: {str(e)}")
            return None
        
    def process_request(self, request: Request) -> Any:
        """
        Process the request and return the result.
        request: The request to process
        returns:
            The result of processing the request
        """
        try:
            # Process the request with the verifier
            verified_request = self._request_verifier.process_requests(request)
            _logger.info(f"Verified request: {verified_request}")
            return verified_request
        except Exception as e:
            _logger.error(f"Error processing request: {e}")
            return None
        
    def map_request(self, request: Request):
        """
        Map the request to a MappedRequest object.
        request: The request to map
        """
        try:
            self._rq_mapper.map_requests(request)
        except Exception as e:
            _logger.error(f"Error mapping request: {e}")
    
    def cleanup(self) -> None:
        """Clean up resources when shutting down"""
        _logger.debug("Cleaning up message queue resources")
        if hasattr(self, '_mq') and self._mq is not None:
            try:
                # Stop receiving notifications
                self._mq.close()
            except Exception as e:
                _logger.error(f"Error closing message queue: {e}")

def main() -> None:
    """
    Main entry point for the Intermediate VoR Partition
    """

    

    time.sleep(5)
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Give other services time to start up
    _logger.info("Intermediate VoR Partition starting...")
    

    verification_ruleset = RuleSet(verfication_ruleset_path)
    feedback_system = FeedbackSystem()
    #rq_verifier = RequestVerifier(verification_ruleset, feedback_system)

    mapping_ruleset = Mapping_RuleSets(mapping_ruleset_path)
    # rq_mapper is initialized in the RequestMessageHandler class
    #rq_mapper = RequestMapper(mapping_ruleset.rulesets, verified_request_registry, feedback_system, 'mapped_requests.db')
    
    rq_handler = RequestMessageHandler("/interface_partition_mq", verification_ruleset, mapping_ruleset, feedback_system, mapped_rq_db_path)
    rq_handler.receive_message(1)
    
    # Use signal-based waiting instead of busy loop
    _logger.info("Intermediate VoR Partition running. Press Ctrl+C to exit.")

    # Use a more efficient sleep pattern - wake up periodically to check status
    while _running:
        # Sleep in shorter intervals to respond to signals more promptly
        time.sleep(5)
    
    # Clean up when exiting
    rq_handler.cleanup()
    _logger.info("Intermediate VoR Partition shutdown complete.")

if __name__ == "__main__":
    main()