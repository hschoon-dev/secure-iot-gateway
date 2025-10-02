"""
------------------------------------------------------------
 Modul:    interface-partition/request_verification.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The Rule and RuleSet classes provide a framework for defining
    and managing verification rules for requests in the VoR
    partition of the Secure IoT Gateway. These classes allow
    for the creation of individual rules, grouping them into
    rule sets, and evaluating requests against these rules to
    determine their validity. The implementation includes
    methods for adding, removing, and evaluating rules, as well
    as handling rule priorities and conditions.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from defusedxml import ElementTree as ET
from datetime import datetime
import logging

# local imports
from request import Request
from feedback_system import FeedbackSystem

_logger = logging.getLogger(__name__)

class Rule:
    def __init__(self, rule_id, description, condition):
        self.rule_id = rule_id
        self.description = description
        self.condition = condition  # Boolean expression as a string

    def validate(self, request):
        try:
            _logger.debug(f"Evaluating rule {self.rule_id} for request {request.id}: {self.condition}")
            return eval(self.condition, {"request": request})
        except Exception:
            _logger.error(f"Error evaluating rule {self.rule_id} for request {request.id}")
            return False

# Template of Request Verification Rule Sets
class RuleSet:
    def __init__(self, xml_file):
        self.rules = []
        self.load_rules_from_xml(xml_file)

    def load_rules_from_xml(self, xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for rule in root.findall('rule'):
            rule_id = rule.get('id')
            description = rule.find('description').text
            condition = rule.find('condition').text
            self.rules.append(Rule(rule_id, description, condition))

    def validate_request(self, request: Request):
        failed_rules = []
        for rule in self.rules:
            if not rule.validate(request):
                failed_rules.append(rule.rule_id)
        return failed_rules

# VoR2 Request Verification      
class RequestVerifier:
    def __init__(self, rule_set, feedback_system):
        self.rule_set: RuleSet = rule_set
        self.queue = []  # Priority queue for requests
        self.verified_request_queue = []
        self.feedback_system: FeedbackSystem = feedback_system
        #self.issuer_registry = issuer_registry

    def process_requests(self, request: Request):
        """Process each request in the priority queue and validate it."""
        # Pop the request with the highest priority
        #request = heapq.heappop(self.queue)
        failed_rules = self.rule_set.validate_request(request)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        # Prepare feedback data
        feedback = {
            "Description": request.description,
            "Priority": request.priority,
            "Verification Result": None,
            "issuer_id": request.issuer_id,
            "request_id": request.id,
            "timestamp": timestamp,
            "step_specific_info": None
        }

        if failed_rules:
            feedback["Verification Result"] = "Rule-based verification failure"
            feedback["step_specific_info"] = f"A specific rule has disapproved the request based on its contents. Failed Rules: {str(failed_rules)}"
            request.Request_verified_status = False
        else:
            request.Request_verified_status = True
            feedback["Verification Result"] = "Verified"
            feedback["step_specific_info"] = "The request is plausible and will be forwarded to the mapping step."
            # ToDo: Dependency-based verification failure
            # Add verified requests to the verified_request_queue
            self.verified_request = request

        # Submit feedback to the feedback system
        _logger.info(f"Request ID {request.id} verification result: {feedback['Verification Result']}")
        self.feedback_system.submit_feedback(feedback)

        # Return the list of verified requests
        return self.verified_request
