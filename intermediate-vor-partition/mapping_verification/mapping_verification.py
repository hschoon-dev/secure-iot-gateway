"""
------------------------------------------------------------
 Modul:    intermediate-vor-partition/mapping_verification.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The VoR step mapping verification includes the mapping rules,
    mapping process, and mapped request storage. The mapping rules
    are defined in an XML file and loaded into the system. The mapping
    process maps incoming requests to affected endpoints based on the
    defined rules. The mapped requests are stored in a TinyDB database.

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
import json
import logging
from datetime import datetime
from typing import Optional
 
# local imports
from request import Request
from feedback_system import FeedbackSystem
from db_manager import DatabaseManager

# TODO: should be in .env
DB_HOST="192.168.178.117"
DB_PORT=3306
DB_USER="iot_gateway"
DB_PASSWORD="your_secure_password"
DB_NAME="secure_iot_gateway"

_logger = logging.getLogger(__name__)


# Template of Mapping Rules
class Mapping_Rule:
    def __init__(
        self,
        rule_id,
        trigger_condition,
        change_description,
        endpoint_identifier,
        unit_of_change,
        mapping_verification_constraint,
    ):
        self.rule_id = rule_id
        self.trigger_condition = trigger_condition
        self.change_description = change_description
        self.endpoint_identifier = endpoint_identifier
        self.unit_of_change = unit_of_change
        self.mapping_verification_constraint = mapping_verification_constraint
 
 
# load rules from xml
class Mapping_RuleSets:
    def __init__(self, xml_file):
        self.rulesets = {}
        self.load_rules_from_xml(xml_file)
 
    def load_rules_from_xml(self, xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for ruleset in root.findall("MappingRuleSet"):
            # load all RuleSet names for impact mapping, key = 'name', value = list of objects
            self.rulesets[ruleset.get("name")] = []
 
            # Iterate through each Rule element
            for rule in ruleset.findall("Rule"):
                rule_id = rule.get("id")
                trigger_condition = rule.find("TriggerCondition").text
                change_description = rule.find("ChangeDescription").text
                endpoint_identifier = rule.find("EndpointIdentifier").text
                unit_of_change = rule.find("UnitOfChange").text
                mapping_verification_constraint = rule.find(
                    "MappingVerificationConstraint"
                ).text
                self.rulesets[ruleset.get("name")].append(
                    Mapping_Rule(
                        rule_id,
                        trigger_condition,
                        change_description,
                        endpoint_identifier,
                        unit_of_change,
                        mapping_verification_constraint,
                    )
                )
        _logger.debug(f"Loaded Mapping Rule Sets: {self.rulesets}")
 
 
# Template of Mapped Requests, Save Mapped Requests to MariaDB
class MappedRequest:
    """
    MariaDB storage schema (one row per mapped request):
        {
            "request_id": str (UNIQUE),
            "generation_timestamp": datetime,
            "description": JSON,
            "impact": str,
            "priority": int,
            "tags": JSON,
            "affected_endpoint_list": JSON (array of endpoint tuples)
        }
    """
 
    def __init__(
        self,
        request_id,
        generation_timestamp,
        description,
        impact,
        priority,
        tags,
        affected_endpoint_list,
        db_manager: DatabaseManager | None,
    ):
        self.request_id = request_id
        self.generation_timestamp = generation_timestamp
        self.description = description
        self.impact = impact
        self.priority = priority
        self.tags = tags
        self.affected_endpoint_list = affected_endpoint_list
        self.db_manager = db_manager
 
    def save_to_db(self) -> bool:
        """
        Upsert mapped request to MariaDB (INSERT ON DUPLICATE KEY UPDATE).
        
        Thread-safe and handles concurrent writes from multiple systems.
        
        Returns:
            True if successful, False otherwise
        """
        if self.db_manager is None:
            _logger.error("Database manager not initialized; cannot save mapped request.")
            return False
 
        try:
            success = self.db_manager.insert_or_update_request(
                request_id=self.request_id,
                generation_timestamp=self.generation_timestamp,
                description=self.description,
                impact=self.impact,
                priority=self.priority,
                tags=self.tags,
                affected_endpoint_list=self.affected_endpoint_list,
            )
 
            if success:
                _logger.info(f"Mapped Request saved to DB: {self.request_id}")
            else:
                _logger.error(f"Failed to save Mapped Request to DB: {self.request_id}")
 
            return success
 
        except Exception as e:
            _logger.error(f"Unexpected error saving mapped request: {e}")
            return False
 
 
class RequestMapper:
    def __init__(
        self,
        mapping_rule_sets,
        feedback_system: FeedbackSystem,
        db_manager: DatabaseManager,
    ):
        # dictonary, key = MappingRuleSet.'name', value = list of Mapping_Rule objects
        self.mapping_rule_sets = mapping_rule_sets
        self.feedback_system: FeedbackSystem = feedback_system
        self.db_manager = db_manager
 
    def map_requests(self, request: Request) -> bool | dict:
        """
        Map an incoming request to affected endpoints based on mapping rules.
        
        Args:
            request: The Request object to map
            
        Returns:
            True if mapping was successful, False otherwise
        """
        affected_endpoint_list = []
        mapping_feedback = {
            "Mapping Result": None,
            "request_id": request.id,
        }
 
        mapping_rule_set = None
        if self.mapping_rule_sets is not None:
            # In the mapping rule set (.xml), find the corresponding mapping rule set based on the impact
            for key in self.mapping_rule_sets:
                if key == request.impact:
                    # After finding the corresponding rule_set, store it in the local variable mapping_rule_set
                    mapping_rule_set = self.mapping_rule_sets[key]
                    break
            
            if mapping_rule_set is None:
                # No matching rule set found
                _logger.warning(
                    f"No matching Mapping Rule Set found for impact: {request.impact}"
                )
                mapping_feedback[
                    "Mapping Result"
                ] = "Mapping failed: no matching mapping rule set for this request"
                self.feedback_system.submit_feedback(mapping_feedback)
                return False
 
            # Map the list of affected endpoints according to the rule set
            for mapping_rule in mapping_rule_set:
                # endpoint_id is the real endpoint name (already in request)
                endpoint_id = request.parameters
 
                # Endpoint change description: relative/absolute (determined based on request.modification)
                if request.modification.endswith("%"):
                    change_type = "relative, " + request.modification
                else:
                    change_type = "absolute, " + request.modification
 
                unit_of_change = mapping_rule.unit_of_change
                mapping_verification_constraint = mapping_rule.mapping_verification_constraint
 
                # Contains endpoint identifiers, endpoint change descriptions, 
                # unit of change, mapping verification constraints
                affected_endpoint = (
                    endpoint_id,
                    change_type,
                    unit_of_change,
                    mapping_verification_constraint,
                )
                affected_endpoint_list.append(affected_endpoint)
 
            _logger.info(f"Mapped Request: {affected_endpoint_list}")
        else:
            _logger.error("Mapping Rule Sets not found")
            return False
 
        mapped_payload = {
            "request_id": request.id,
            "generation_timestamp": str(request.timestamp),
            "description": list(request.description),
            "impact": request.impact,
            "priority": int(request.priority),
            "affected_endpoint_list": affected_endpoint_list,
        }

        # In the typed gRPC mode the next stage acknowledges application before
        # the interface receives an ACK. The production default continues to
        # persist the same payload in MariaDB for the existing polling stage.
        if self.db_manager is None:
            mapping_feedback["Mapping Result"] = "Mapping completed"
            self.feedback_system.submit_feedback(mapping_feedback)
            return mapped_payload

        # Create and save the mapped request
        mapped_request = MappedRequest(
            request.id,
            request.timestamp,
            request.description,
            request.impact,
            request.priority,
            None,
            affected_endpoint_list,
            self.db_manager,
        )
 
        if mapped_request.save_to_db():
            mapping_feedback["Mapping Result"] = "Mapping completed"
            _logger.info(f"Mapping completed for request ID: {request.id}")
            self.feedback_system.submit_feedback(mapping_feedback)
            return True
        else:
            _logger.error(f"Failed to save Mapped Request to DB: {mapped_request.request_id}")
            mapping_feedback["Mapping Result"] = "Mapping failed: database error"
            self.feedback_system.submit_feedback(mapping_feedback)
            return False
