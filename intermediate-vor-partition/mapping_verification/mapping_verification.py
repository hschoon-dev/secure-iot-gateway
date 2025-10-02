"""
------------------------------------------------------------
 Modul:    interface-partition/mapping_verification.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The VoR step mapping verification includes the mapping rules,
    mapping process, and mapped request storage. The mapping rules
    are defined in an XML file and loaded into the system. The mapping
    process maps incoming requests to affected endpoints based on the
    defined rules. The mapped requests are stored in a SQLite database.

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
import sqlite3
import json
import logging

# local imports
from request import Request
from feedback_system import FeedbackSystem

_logger = logging.getLogger(__name__)


#Template of Mapping Rules
class Mapping_Rule:
  def __init__(self, rule_id, trigger_condition, change_description, endpoint_identifier, unit_of_change, mapping_verification_constraint):
        self.rule_id = rule_id
        self.trigger_condition = trigger_condition
        self.change_description = change_description
        self.endpoint_identifier = endpoint_identifier
        # self.mapping_verification_constraint_absolute = mapping_verification_constraint_absolute
        self.unit_of_change = unit_of_change
        self.mapping_verification_constraint = mapping_verification_constraint
        

    # def validate(self, request):
    #     try:
    #         return eval(self.condition, {"request": request})
    #     except Exception:
    #         return False


# loade rules from xml
class Mapping_RuleSets:
    def __init__(self, xml_file):
        self.rulesets = {}
        self.load_rules_from_xml(xml_file)

    def load_rules_from_xml(self, xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for ruleset in root.findall('MappingRuleSet'):
            self.rulesets[ruleset.get('name')] = []         # load all RuleSet names for impact mapping, key = 'name', value = list of objects

            # Iterate through each Rule element
            for rule in ruleset.findall('Rule'):
                rule_id = rule.get('id')
                trigger_condition = rule.find('TriggerCondition').text
                change_description = rule.find('ChangeDescription').text
                endpoint_identifier = rule.find('EndpointIdentifier').text
                unit_of_change = rule.find('UnitOfChange').text
                mapping_verification_constraint = rule.find("MappingVerificationConstraint").text
                self.rulesets[ruleset.get('name')].append(Mapping_Rule(rule_id, trigger_condition, change_description, endpoint_identifier, unit_of_change, mapping_verification_constraint))
        _logger.debug(f"Loaded Mapping Rule Sets: {self.rulesets}")
    

# Template of Mapped Requests, Save Mapped Requests directly to a SQLite database
class MappedRequest:
    def __init__(self, request_id, generation_timestamp, description, impact, priority, tags, affected_endpoint_list, db_name):
        self.request_id = request_id
        self.generation_timestamp = generation_timestamp
        self.description = description
        self.impact = impact
        self.priority = priority
        self.tags = tags
        self.affected_endpoint_list = affected_endpoint_list
        self.db_name = db_name
        # self.save_to_db()

        self._init_database()  # Initialize the database when creating a MappedRequest instance

    def _init_database(self):
        """Initialize the database and create the necessary tables if they don't exist."""
        try:
            db_connection = sqlite3.connect(self.db_name)
            cursor = db_connection.cursor()
            
            # Create the mapped_requests table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mapped_requests (
                    request_id TEXT PRIMARY KEY,
                    generation_timestamp TEXT NOT NULL,
                    description TEXT,
                    impact TEXT,
                    priority INTEGER,
                    tags TEXT,
                    affected_endpoint_list TEXT
                )
            """)
            
            db_connection.commit()
            _logger.debug(f"Database initialized: {self.db_name}")
        except sqlite3.Error as e:
            _logger.error(f"SQLite Error during database initialization: {e}")
        finally:
            if 'db_connection' in locals() and db_connection:
                db_connection.close()

    def save_to_db(self):
        # Convert the affected_endpoint_list to a JSON string to store the Python list
        affected_endpoint_list_json = json.dumps(self.affected_endpoint_list)
        # Convert the generated timestamp to a string
        #generation_timestamp_str = self.generation_timestamp.isoformat()

        # Convert the description to a JSON string if it's a dictionary
        description_str = json.dumps(self.description) if isinstance(self.description, dict) else self.description
        # Convert the impact to a JSON string if it's a dictionary
        impact_str = json.dumps(self.impact) if isinstance(self.impact, dict) else self.impact

        try:
            db_connection = sqlite3.connect(self.db_name)
            cursor = db_connection.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO mapped_requests 
                (request_id, generation_timestamp, description, impact, priority, tags, affected_endpoint_list) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (self.request_id, self.generation_timestamp, description_str, impact_str,
                self.priority, self.tags, affected_endpoint_list_json))
            db_connection.commit()
            return True
        except sqlite3.OperationalError as e:
            _logger.error(f"SQLite Error: {e}")
            return False
        finally:         # Ensure the connection is closed to prevent resource leakage
            if db_connection:
                db_connection.close()
        

class RequestMapper:
    def __init__(self, mapping_rule_sets, feedback_system, db_name):
        self.mapping_rule_sets = mapping_rule_sets                      # dictonary, key = MappingRuleSet.'name', value = list of Mapping_Rule objects
        #self.verified_request_registry = verified_request_registry
        self.feedback_system: FeedbackSystem = feedback_system
        # self.mapped_requests = []
        self.db_name = db_name
        #self.map_requests()         # Execute map_requests() when instantiating the class

    
    def map_requests(self, request: Request):
        affected_endpoint_list = []        
        mapping_feedback = { # TODO: Determine how much feedback information is useful, needed and secure
            # "Description": request.description,
            # "Priority": request.priority,
            "Mapping Result": None,        
            # "issuer_id": request.issuer_id,
            "request_id": request.id,
            # "timestamp": timestamp,
            # "step_specific_info": None
        }
        mapping_rule_set = None
        mapping_rule: Mapping_Rule = None
        if self.mapping_rule_sets is not None:
        # In the mapping rule set (.xml), find the corresponding mapping rule set based on the impact
            for key in self.mapping_rule_sets:
                if key == request.impact:
                    mapping_rule_set = self.mapping_rule_sets[key] # After finding the corresponding rule_set, store it in the local variable mapping_rule_set
                    break
                else:                                              # else is executed only if there is no break in the for statement
                    #  Print Mapping Failure when the corresponding rule set is not found in the mapping ruleset
                    _logger.warning(f"No matching Mapping Rule Set found for impact: {request.impact}")
                    mapping_feedback["Mapping Result"] = "Mapping failed: no matching mapping rule set for this request"  
                    self.feedback_system.submit_feedback(mapping_feedback)     
                    continue

            if mapping_rule_set is not None:         # If the mapping rule set is not found, return and do not continue with the mapping process
                # Map the list of affected endpoints according to the rule set, and find out the mapping verification constraints that need to be checked, store them, and pass them to the next step
                for mapping_rule in mapping_rule_set:               # mapping_rule is a Mapping_Rule class object, and mapping_rule_set is a list of Mapping_Rule class objects
                    endpoint_id = mapping_rule.endpoint_identifier + "_" + request.parameters
                    # Endpoint change description, which includes two types: relative/absolute (determined based on the request.modification)
                    if request.modification.endswith("%"):      # corresponding mapping verification constraints
                        change_type = "relative, " + request.modification
                    else:
                        change_type = "absolute, " + request.modification
                    unit_of_change = mapping_rule.unit_of_change
                    mapping_verification_constraint = mapping_rule.mapping_verification_constraint      # The mapping verification only includes absolute check values, since most of the OT project's parameters will not be relative values.
                    affected_endpoint = (endpoint_id, change_type, unit_of_change, mapping_verification_constraint)     # 包含endpoint identifiers, endpoint change descriptions('relative/absolute, modification', unit of change), mapping verification constraints 
                    affected_endpoint_list.append(affected_endpoint)
            else:
                _logger.warning(f"Mapping Rule Set not found for impact: {request.impact}")
                return

            _logger.info(f"Mapped Request: {affected_endpoint_list}")
        else:
            _logger.error("Mapping Rule Sets not found")
            return 

        mapped_request = MappedRequest(request.id, request.timestamp, request.description, request.impact, request.priority, None, affected_endpoint_list, self.db_name)
        
        if mapped_request.save_to_db():
            mapping_feedback["Mapping Result"] = "Mapping completed"
            _logger.info(f"Mapping completed for request ID: {request.id}")
            self.feedback_system.submit_feedback(mapping_feedback)
            _logger.info(f"Mapped Request saved to DB: {mapped_request.request_id}")
        else:
            _logger.error(f"Failed to save Mapped Request to DB: {mapped_request.request_id}")