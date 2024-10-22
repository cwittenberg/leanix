import pprint
from datetime import datetime,timezone, timedelta

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

import os
import json
import requests
import warnings
from urllib3.exceptions import InsecureRequestWarning

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


# Suppress only the InsecureRequestWarning from urllib3
warnings.simplefilter('ignore', InsecureRequestWarning)

class LeanIXAPI:
    _coupa_tag = None
    _active_tag = None
    _expired_tag = None

    def __init__(self, api_token, auth_url, request_url, metrics_url=None, search_base_url=None):
        self.api_token = api_token
        self.auth_url = auth_url
        self.request_url = request_url
        self.metrics_url = metrics_url
        self.search_base_url = search_base_url

        self.header = self._authenticate()
        self.header['x-graphql-enable-extensions'] = 'true'
        self.upload_url = self.request_url + '/upload'

        for tag in self.all_tags():
            if tag['node']['name'] == "Coupa":
                self._coupa_tag = tag['node']['id']
            if tag['node']['name'] == "Active":
                self._active_tag = tag['node']['id']
            if tag['node']['name'] == "Expired":
                self._expired_tag = tag['node']['id']


    def _authenticate(self):
        # Get the bearer token
        response = requests.post(self.auth_url, auth=('apitoken', self.api_token),
                                 data={'grant_type': 'client_credentials'}, verify=False)
        response.raise_for_status()
        access_token = response.json()['access_token']
        return {'Authorization': 'Bearer ' + access_token}
    
    @retry(
        stop=stop_after_attempt(3),  # Stop after 5 attempts
        wait=wait_exponential(multiplier=1, min=2, max=60),  # Exponential backoff: wait 2^x * 1 (where x is the attempt number)
        retry=retry_if_exception_type(requests.exceptions.RequestException),  # Retry on any requests exceptions
        before_sleep=before_sleep_log(logger, logging.INFO)  # Log before retrying
    )
    def _call_generic(self, url, method="GET", payload=None):
        try:
            if method == "GET":
                response = requests.get(url, headers=self.header, verify=False)
            elif method == "POST":
                response = requests.post(url, headers=self.header, json=payload, verify=False)
            else:
                raise ValueError("Invalid HTTP method. Only GET and POST are supported.")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            raise

        resp = response.json()

        if "extensions" in resp:
            if "warnings in resp['extensions']":
                print("*************WARNINGS****************")
                print(resp['extensions']['warnings'])
            

        return resp
    
    def get_factsheet_by_id(self, factsheet_id, fields=None):
        """
        Retrieve the factsheet by its ID with dynamic fields.

        Args:
            factsheet_id (str): The ID of the factsheet.
            fields (str): Optional. The GraphQL fields to retrieve, formatted as a string.

        Returns:
            dict: The factsheet data if found, None otherwise.
        """

        if fields is None:
            fields = ""

        # Set default fields if none are provided
        fields = f"""
            id
            name
            type
            description
            status
            category
            {fields}
        """

        query = f"""
        {{
            factSheet(id: "{factsheet_id}") {{
                {fields}
            }}
        }}
        """
        response = self._call(query)

        if 'data' in response and response is not None: 
            if response['data'] is not None:
                if 'factSheet' in response['data']:                
                    return response['data']['factSheet']
        
        print("Error occured during factsheet retrieval for ID " + factsheet_id)
        print(response)
        return None


    @retry(
        stop=stop_after_attempt(3),  # Stop after 5 attempts
        wait=wait_exponential(multiplier=1, min=2, max=60),  # Exponential backoff: wait 2^x * 1 (where x is the attempt number)
        retry=retry_if_exception_type(requests.exceptions.RequestException),  # Retry on any requests exceptions
        before_sleep=before_sleep_log(logger, logging.INFO)  # Log before retrying
    )
    def _call(self, query, dump=True):
        data = {"query": query}

        if dump:
            json_data = json.dumps(data)
        else:
            json_data = data


        try:
            # print(json_data)  # For debugging purposes
            response = requests.post(url=self.request_url, headers=self.header, data=json_data, verify=False, timeout=10)
            # print(response.text)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if response:
                # check if status_code attribute exists
                if hasattr(response, 'status_code'):
                    #check if error is a 401
                    if response.status_code == 401:
                        print("Unauthorized. Re-authenticating...")
                        self.header = self._authenticate()
                        return self._call(query, dump)
                    else:
                        # print(response.text)
                        pass
            
            print(f"Request failed: {e}")
            raise
        
        return response.json()


    def create_factsheet(self, type, name, subtype=None):
        # Create the GraphQL mutation with or without the patches for category
        mutation = """
        mutation($input: BaseFactSheetInput!, $patches: [Patch]) {
            createFactSheet(input: $input, patches: $patches) {
                factSheet {
                    id
                    name
                    displayName
                    rev
                    type
                    category
                }
            }
        }
        """
        
        # Set up the variables
        if subtype:
            variables = {
                "input": {
                    "name": name,
                    "type": type
                },
                "patches": [
                    {
                        "op": "replace",
                        "path": "/category",
                        "value": subtype
                    }
                ]
            }
            print(f"Creating {type} with subtype {subtype}: {name}")
        else:
            variables = {
                "input": {
                    "name": name,
                    "type": type
                },
                "patches": []
            }
            print(f"Creating {type}: {name}")
        
        # Create the transport with the given headers
        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        # Create a GraphQL client
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Execute the mutation
        response = client.execute(gql(mutation), variable_values=variables)

        # Handle error
        if 'errors' in response:
            print(response)
            return None

        return response['createFactSheet']['factSheet']['id']
        


    def modify_factsheet(self, factsheet_id, patches):
        # Create the GraphQL mutation
        mutation = gql("""
        mutation($patches: [Patch]!) {
        updateFactSheet(id: "%s", patches: $patches) {
            factSheet {
                id
                name
                tags {
                    id
                    name
                }
            }
        }
        }
        """ % factsheet_id)

        # Set up the variables
        variables = {
            "patches": patches
        }

        # Create the transport with the given headers
        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        # Create a GraphQL client
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Execute the mutation
        response = client.execute(mutation, variable_values=variables)


        return response['updateFactSheet']['factSheet']['id']
    
    def get_factsheet_type_by_id(self, factsheet_id):
        query = f"""
        {{
            factSheet(id: "{factsheet_id}") {{
                id
                type
            }}
        }}
        """
        response = self._call(query)

        if 'data' in response and 'factSheet' in response['data']:
            return response['data']['factSheet']['type']
        else:
            return None
        
    def create_if_not_exists(self, type, name, subtype=None, createAsChildOf=None, relationshipName=None, cost=None):
        factsheet_id = self.find_by_name(type, name)

        precreated=False

        fs_id = None
        if factsheet_id:
            precreated=True
            fs_id = factsheet_id
        else:
            fs_id = self.create_factsheet(type, name, subtype)

        try:
            # detect if we need to create a relationship
            if createAsChildOf is not None:
                source_fs_type = self.get_factsheet_type_by_id(createAsChildOf)

                if relationshipName is None:
                    raise ValueError("relationshipName must be provided if createAsChildOf is set.")
                else:
                    self.create_relation_if_not_exists(createAsChildOf, fs_id, source_fs_type, relationshipName, cost=cost)

        except Exception as e:
            print(f"Error creating relationship: {e}")

            if precreated:
                print(f"Deleting pre-created factsheet {fs_id}")
                self.archive_factsheet(fs_id)

        return fs_id
        
    def factsheet_exists(self, factsheet_id):
        """
        Check if a factsheet of the given type and ID exists.

        Args:
            factsheet_type (str): The type of the factsheet (e.g., "Application", "ITComponent").
            factsheet_id (str): The ID of the factsheet.

        Returns:
            bool: True if the factsheet exists and matches the given type, False otherwise.
        """
        try:
            retrieved_type = self.get_factsheet_type_by_id(factsheet_id)
            if retrieved_type is None:
                return False
            return True
        except Exception as e:
            print(f"Error checking factsheet existence: {e}")
            return False

    
    def _custom_json_format(self,value_dict):
        # Build the inner JSON string with proper escaping
        items = []
        for key, value in value_dict.items():
            if isinstance(value, str):
                # Escape any backslashes and double quotes in the string value
                # escaped_value = value.replace('\\', '\\\\').replace('"', '\\"')
                # items.append('\\"%s\\":\\"%s\\"' % (key, escaped_value))
                # {\"costTotalAnnual\":%f,\"factSheetId\":\"%s\"}
                items.append('\"%s\":\"%s\"' % (key, value))
            elif isinstance(value, float):
                items.append('\"%s\":\"%f\"' % (key, value))
            else:
                items.append('\"%s\":\"' + str(value) + '\"' % (key))
            
        value_content = ','.join(items)
        # Wrap with curly braces and then with double quotes
        value_str = "{%s}" % value_content
        return value_str
    




    def add_tag_to_factsheet(self, factsheet_id, tag_id):        
        # Patches to apply
        patches = [
            {
                "op": "add",
                "path": "/tags",
                "value": '[{"tagId":"' + tag_id + '"}]'
            }
        ]

        return self.modify_factsheet(factsheet_id, patches)
    
    def create_relation_if_not_exists(self, source_id, target_id, on_factsheet_type, relation_name, cost=None):
        query = """
        {
            factSheet(id: "%s") {
                id
                name
                ... on %s {
                    %s {
                        edges {
                            node {
                                factSheet {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
        """ % (source_id, on_factsheet_type, relation_name)
        response = self._call(query)

        fact_sheet = response.get('data', {}).get('factSheet')
        if not fact_sheet:
            raise ValueError("FactSheet not found in the response.")
        
        relationships = fact_sheet.get(relation_name, {}).get('edges', [])
        
        if not relationships:
            return self.create_relation_with_costs(target_id, source_id, cost, relation_name)
        else:            
            #iterate and check if target_id is in the relationships
            for edge in relationships:
                if edge['node']['factSheet']['id'] == target_id:
                    print(f"Relation already exists between {source_id} --> {target_id}")

                    # update costs if provided
                    if cost is not None:
                        print(f"Updating costs for relation {source_id} --> {target_id}")
                        return self.create_relation_with_costs(target_id, source_id, cost, relation_name, op="replace")

                    return None
            
            print("Creating relation between " + source_id + " --> " + target_id)
            return self.create_relation_with_costs(target_id, source_id, cost, relation_name)
        


    def find_by_name(self, type, name):
        query = """
        {
            allFactSheets(filter: {facetFilters: [{facetKey: "FactSheetTypes", keys: ["%s"]}], fullTextSearch: "%s"}) {
                edges {
                    node {
                        id
                        name                   
                    }
                }
            }
        }
        """ % (type, name)
        response = self._call(query)

        # Check if any IT Component matches the name
        for edge in response['data']['allFactSheets']['edges']:
            if edge['node']['name'].lower() == name.lower():
                return edge['node']['id']
        return None
    

    def search(self, query):
        response = self._call_generic(f"{self.search_base_url}services/pathfinder/v1/suggestions?q={query}")

        result = []
        for s in response['data']:
            for item in s['suggestions']:
                result.append({
                    'id': item['objectId'],
                    'name': item['displayName'],
                    'type': item['type'],
                    'category': item['category']
                })

                for r in item['reasons']:
                    if r['field'] == 'externalId':
                        result[-1]['externalId'] = r['value']

        return result
    
    
    def get_relationships(self, factsheet_id, source, target):
        query = """
        {
            factSheet(id: "%s") {
                id
                name
                ... on %s {
                    %s {
                        edges {
                            node {
                                factSheet {
                                    id
                                    name
                                }
                            }
                        }
                    }
                }
            }
        }
        """ % (factsheet_id, source, target)

        response = self._call(query)


        # Check if the factSheet exists in the response and then the relationships
        fact_sheet = response.get('data', {}).get('factSheet')
        if not fact_sheet:
            raise ValueError("FactSheet not found in the response.")
        
        relationships = fact_sheet.get(target, {}).get('edges', [])
        
        if not relationships:
            return []  # or raise an exception if you expect at least one relationship
        
        # Extract all related IT Component IDs and Names
        return [
            {
                'id': relationship.get('node', {}).get('factSheet', {}).get('id'),
                'name': relationship.get('node', {}).get('factSheet', {}).get('name')
            }
            for relationship in relationships if relationship.get('node', {}).get('factSheet')
        ]
    
    def get_relationship_ids(self, factsheet_id, factsheet_type, relationship_name):    
        query = """
        {
            factSheet(id: "%s") {
                id
                name
                ... on %s {
                    %s {
                        edges {
                            node {
                                id
                                factSheet {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
        """ % (factsheet_id, factsheet_type, relationship_name)


        response = self._call(query)
        
        try:
            # Check if the Fact Sheet exists in the response
            fact_sheet = response.get('data', {}).get('factSheet')
        except:
            print(response)
            
            print("ERROR occured. Exiting prematurely...")
            exit(0)

        if not fact_sheet:
            return []

        # Access the relation within the ITComponent fragment
        relations = fact_sheet.get(relationship_name, {}).get('edges', [])


        rels = []

        for edge in relations: 
            rels.append({
                'relationship_id': edge['node']['id'],
                'to': edge['node']['factSheet']['id']
            })

        return rels



    def get_all_components(self, ignoreHomegrown=True):
        query = """
        {
            allFactSheets(filter: {facetFilters: [{facetKey: "FactSheetTypes", keys: ["ITComponent"]}]}) {
                edges {
                    node {
                        ... on ITComponent {
                            id
                            name
                            isOpenSource

                            relITComponentToProvider { 
                                edges {
                                    node {
                                        factSheet {
                                            ... on Provider {                                            
                                                name
                                            }
                                        }
                                    }
                                }
                            }

                            relITComponentToApplication { 
                                edges {
                                    node {
                                        factSheet {
                                            ... on Application {                                            
                                                name
                                                category
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        response = self._call(query)

        # Collect all applications
        applications = []

        # get tags from response        
        for edge in response['data']['allFactSheets']['edges']:
            item = {
                'id': edge['node']['id'],
                'component_name': edge['node']['name'],
                'provider': None,
                'applications': set(),
                'isOpenSource': edge['node']['isOpenSource'],
            }

            # Assign provider if available
            if 'relITComponentToProvider' in edge['node']:
                if 'edges' in edge['node']['relITComponentToProvider']:
                    if len(edge['node']['relITComponentToProvider']['edges']) > 0:
                        provider = edge['node']['relITComponentToProvider']['edges'][0]['node']['factSheet']['name']
                        item['provider'] = provider

            moveNext=False

            if 'relITComponentToApplication' in edge['node']:
                if 'edges' in edge['node']['relITComponentToApplication']:
                    for edge in edge['node']['relITComponentToApplication']['edges']:
                        provider = edge['node']['factSheet']['name']
                        category = edge['node']['factSheet']['category']

                        if ignoreHomegrown and category == "Homegrown":
                            #ignore such applications
                            moveNext = True
                            break
                        else:
                            item['applications'].add(provider)

            if moveNext:
                continue
            else:
                applications.append(item)

        return applications



    def get_all_contracts(self, tagFilter = []):
        query = """
        {
            allFactSheets(filter: {facetFilters: [{facetKey: "FactSheetTypes", keys: ["Contract"]}]}) {
                edges {
                    node {
                        ... on Contract {
                            id
                            name                            
                            externalId {
                                externalId
                            }
                            tags {
                                id
                                name
                            }

                            relContractToProvider { 
                                edges {
                                    node {
                                        factSheet {
                                            ... on Provider {                                            
                                                name
                                                alias
                                            }
                                        }
                                    }
                                }
                            }

                            relContractToApplication { 
                                edges {
                                    node {
                                        factSheet {
                                            ... on Application {                                            
                                                name
                                                alias
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """


        response = self._call(query)

        # Collect all contracts
        contracts = []

        for edge in response['data']['allFactSheets']['edges']:
            item = {
                'id': edge['node']['id'],
                'name': edge['node']['name'],
                'externalId': None,
                'provider': None,
                'provider_alias' : None,
                'applications': []
            }

            theTags = set()
            for t in edge['node']['tags']:
                theTags.add(t['name'])

            # check if all tagFilter are in theTags
            if len(tagFilter) > 0:
                if not all(x in theTags for x in tagFilter):
                    print("Skipping contract (not passing filter): " + item['name'])
                    continue            

            #stamp externalId on the record
            if 'externalId' in edge['node']:
                if edge['node']['externalId'] != "" and edge['node']['externalId'] is not None: 
                    if 'externalId' in edge['node']['externalId']:
                        if edge['node']['externalId']['externalId'] != "":
                            item['externalId'] = edge['node']['externalId']['externalId']

            if 'relContractToProvider' in edge['node']:
                if 'edges' in edge['node']['relContractToProvider']:
                    if len(edge['node']['relContractToProvider']['edges']) > 0:
                        provider = edge['node']['relContractToProvider']['edges'][0]['node']['factSheet']['name']
                        item['provider'] = provider

                        if 'alias' in edge['node']['relContractToProvider']['edges'][0]['node']['factSheet']:
                            alias = edge['node']['relContractToProvider']['edges'][0]['node']['factSheet']['alias']
                            item['provider_alias'] = alias

            if 'relContractToApplication' in edge['node']:
                if 'edges' in edge['node']['relContractToApplication']:
                    for edge in edge['node']['relContractToApplication']['edges']:
                        application = edge['node']['factSheet']['name']
                        item['applications'].append(application)

                        if 'alias' in edge['node']['factSheet']:
                            alias = edge['node']['factSheet']['alias']
                            if alias is not None and alias != "":
                                item['applications'].append(alias)

            contracts.append(item)

        return contracts


    def get_all(self, type, specificSubtype=None):
        if specificSubtype is None:            
            query = """
            {
                allFactSheets(filter: {facetFilters: [{facetKey: "FactSheetTypes", keys: ["%s"]}]}) {
                    edges {
                        node {
                            id
                            name              
                            ...on %s {
                                externalId {
                                    externalId
                                }
                            }

                            ...on Application{
                                alias
                            }
                        }
                    }
                }
            }
            """ % (type, type)
        else:
            query = """
            {
                allFactSheets(filter: {facetFilters: [
                        {facetKey: "FactSheetTypes",  keys: ["%s"]},
                        {facetKey: "category", keys: ["%s"]}
                    ]
                }) {
                    edges {
                        node {
                            id
                            name              
                            ...on %s {
                                externalId {
                                    externalId
                                }
                            }

                            ...on Application{
                                alias
                            }
                        }
                    }
                }
            }
            """ % (type, specificSubtype, type)
        
        response = self._call(query)

        # Collect all applications with their ids
        applications = []

        for edge in response['data']['allFactSheets']['edges']:
            item = {
                'id': edge['node']['id'],
                'name': edge['node']['name'],
                'externalId': None,
                'alias': None
            }

            #stamp externalId on the record
            if 'externalId' in edge['node']:
                if edge['node']['externalId'] != "" and edge['node']['externalId'] is not None: 
                    if 'externalId' in edge['node']['externalId']:
                        if edge['node']['externalId']['externalId'] != "":
                            item['externalId'] = edge['node']['externalId']['externalId']

            
            if 'alias' in edge['node']:
                if edge['node']['alias'] != "":
                    item['alias'] = edge['node']['alias']
            
            applications.append(item)

        return applications

    def create_it_component(self, name):
        return self.create_factsheet("ITComponent", name)
    
    def create_application(self, name):
        return self.create_factsheet("Application", name)
    
    
    def create_contract(self, supplierName, name, description, subtype="Contract", isActive=True, isExpired=False, contractValue=0, numberOfSeats=None, volumeType="License", phasein_date=None, active_date=None, notice_date=None, eol_date=None, externalId="", externalUrl="", applicationId="", domains=[], managedByName=None, managedByEmail=None, currency="EUR", additionalTags=[]):
        # set None to ""
        if phasein_date is None:
            phasein_date = ""
        if active_date is None:
            active_date = ""
        if notice_date is None:
            notice_date = ""
        if eol_date is None:
            eol_date = ""
        
        # Define the GraphQL mutation with variables
        mutation = gql("""
        mutation($input: BaseFactSheetInput!, $patches: [Patch]) {
            createFactSheet(input: $input, patches: $patches) {
                factSheet {
                    id
                    name
                    displayName
                    rev
                    type
                    category                    
                    tags {
                        id
                        name
                    }
                    ...on Domain {
                        DomainLifecycle:
                            lifecycle{
                                asString phases{phase startDate}
                            }
                        }
                    ...on Provider{
                            ProviderLifecycle:
                            lifecycle{
                                asString phases{phase startDate}
                            }
                        }
                    ...on Application{
                        lxHostingType
                    }
                    ... on Contract {
                        ContractValue
                        NumberOfSeats
                        VolumeType
                        description
                        ManagedBy
                        contractDifferentCurrency
                        contractCurrency
                        
                        externalId{
                            externalId
                            comment
                            externalUrl
                            status
                        }
                       
                        ContractLifecycle:
                            lifecycle{
                                asString phases{phase startDate milestoneId
                            }                        
                       }                    
                    }
                }
            }
        }
        """)

        # Define the input for the contract creation
        input_data = {
            "name": name,
            "type": "Contract",
            "permittedReadACL": [],
            "permittedWriteACL": []
        }

        patches = []
        
        if isActive:
            patches.append({
                "op": "add",
                "path": "/tags",
                "value": '[{"tagId":"' + self._active_tag + '"}]'
            })
        
        if isExpired:
            patches.append({
                "op": "add",
                "path": "/tags",
                "value": '[{"tagId":"' + self._expired_tag + '"}]'
            })

        if additionalTags and len(additionalTags) == 0:
            if volumeType == "License":
                patches.append({
                    "op": "add",
                    "path": "/tags",
                    "value": '[{"tagId":"0ffd0620-24d4-4d06-995f-aa6bff8744dd"}]'
                })

        if currency != "EUR":
            patches.append({
                "op": "replace",
                "path": "/contractDifferentCurrency",
                "value": "Yes"
            })
        else:
            patches.append({
                "op": "replace",
                "path": "/contractDifferentCurrency",
                "value": "No"
            })

        # Conditionally add the externalId
        externalObj = {
            "externalId": str(externalId),
        }

        if externalUrl is not None and externalUrl != "":
            externalObj["externalUrl"] = externalUrl

        #"{\"externalId\":\"" + str(externalId) + "\", \"externalUrl\":\"" + str(externalUrl) + "\", \"status\":\"\"}"
        externalStr = json.dumps(externalObj)
        
        # print(externalStr)

        if not numberOfSeats or numberOfSeats == "" or numberOfSeats == "0" or numberOfSeats == 0:
            numberOfSeats = "1"

        # Define the patches to set the subtype
        # merge with patches
        patches.extend([ 
            {
                "op": "replace",
                "path": "/category",
                "value": subtype
            },
            {
                "op": "replace",
                "path": "/contractCurrency",
                "value": currency
            },
            {
                "op": "add",
                "path": "/tags",
                "value": '[{"tagId":"' + self._coupa_tag + '"}]'
            },
            {
                "op": "replace",
                "path": "/ContractValue",
                "value": contractValue
            },
            {
                "op": "replace",
                "path": "/NumberOfSeats",
                "value": numberOfSeats
            },
            {
                "op": "replace",
                "path": "/VolumeType",
                "value": volumeType
            },
            {
                "op": "replace",
                "path": "/description",
                "value": description
            },
            {
                "op": "replace",
                "path": "/externalId",
                "value": externalStr
            },            
        ])

        if additionalTags and len(additionalTags) > 0:
            for tag in additionalTags:
                patches.append({
                    "op": "add",
                    "path": "/tags",
                    "value": '[{"tagId":"' + tag + '"}]'
                })

        if managedByName is not None and managedByEmail is not None:
            patches.append({
                "op": "replace",
                "path": "/ManagedBy",
                "value": managedByName + " <" + managedByEmail + ">"
            })
        elif managedByName is not None and managedByEmail is None:
            patches.append({
                "op": "replace",
                "path": "/ManagedBy",
                "value": managedByName
            })
        else:
            pass

        if applicationId:
            patches.append({
                "op": "add",
                "path": "/relContractToApplication/new_" + applicationId,
                "value": "{\"factSheetId\":\"" + applicationId + "\"}"
            })

        if domains and len(domains) > 0:
            for domain in domains:
                patches.append({
                    "op": "add",
                    "path": "/relContractToDomain/new_" + domain['id'],
                    "value": "{\"factSheetId\":\"" + domain['id'] + "\"}"
                })

        # add lifecycle phases
        # Conditionally build and add the lifecycle patch if any date is provided
        lifecycle_phases = []

        if phasein_date != "" and phasein_date is not None:
            lifecycle_phases.append({"phase": "phaseIn", "startDate": phasein_date})

        if active_date != "" and active_date is not None:
            lifecycle_phases.append({"phase": "active", "startDate": active_date})

        if notice_date != "" and notice_date is not None:
            lifecycle_phases.append({"phase": "phaseOut", "startDate": notice_date})

        if eol_date != "" and eol_date is not None:
            lifecycle_phases.append({"phase": "endOfLife", "startDate": eol_date})

        print(lifecycle_phases)

        if lifecycle_phases:
            lifecycle_value = json.dumps({"phases": lifecycle_phases})
            patches.append({
                "op": "replace",
                "path": "/lifecycle",
                "value": lifecycle_value
            })

        # format supplier
        supplierName = supplierName.replace("_", " ").strip()

        # Lookup provider by name
        providerId = self.find_by_name("Provider", supplierName)

    
        if not providerId:
            #create new provider
            providerId = self.create_factsheet("Provider", supplierName)

        if providerId:
            patches.append({
                "op": "add",
                "path": "/relContractToProvider/new_" + providerId,
                "value": "{\"factSheetId\":\"" + providerId + "\"}"
            })

        # Combine the input and patches into the variables for the mutation
        variables = {
            "input": input_data,
            "patches": patches
        }

        # Set up the transport with the given headers
        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        # Create a GraphQL client
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Execute the mutation with the variables
        response = client.execute(mutation, variable_values=variables)

        return response['createFactSheet']['factSheet']['id']


    def create_relation_with_costs(self, app_id, itc_id, costs, relation="relITComponentToApplication", op="add"):
        if costs is None:
            costs = 0

        if op == "add":
            path = "/%s/new_%s" % (relation, app_id)
        if op == "replace":
            #lookup the relationship id
            kind = self.get_factsheet_type_by_id(itc_id)
            relationships = self.get_relationship_ids(itc_id, kind, relation)
            for entry in relationships:
                if entry['to'] == app_id:
                    path = "/%s/%s" % (relation, entry['relationship_id'])
                    break

        if costs > 0:
            query = """
            mutation {
                updateFactSheet(id: "%s", 
                                patches: [{op: %s, path: "%s", 
                                        value: "{\\\"factSheetId\\\": \\\"%s\\\",\\\"costTotalAnnual\\\": %s}"}]) {
                    factSheet {
                        id
                    }
                }
            }
            """ % (itc_id, op, path, app_id, costs)
        else:
            query = """
            mutation {
                updateFactSheet(id: "%s", 
                                patches: [{op: %s, path: "%s", 
                                        value: "{\\\"factSheetId\\\": \\\"%s\\\"}"}]) {
                    factSheet {
                        id
                    }
                }
            }
            """ % (itc_id, op, path, app_id)

        print("Create relation with costs: " + itc_id + "->" + app_id + " = " + str(costs))
        resp = self._call(query)
        print(resp)

    def create_relation_between_contract_and_provider(self, contract_id, provider_id):
        query = """
        mutation {
            updateFactSheet(id: "%s", 
                            patches: [{op: add, path: "/relContractToProvider/new_1", 
                                    value: "{\\\"factSheetId\\\": \\\"%s\\\"}"}]) {
                factSheet {
                    id
                }
            }
        }
        """ % (contract_id, provider_id)
        print("Create relation between Contract: " + contract_id + " and Provider: " + provider_id)
        self._call(query)

    def all_tags(self):
        query = """
        {
            allTags {
                edges {
                    node {
                        id
                        name
                    }
                }
            }
        }
        """

        response = self._call(query)
        return response['data']['allTags']['edges']
        


    def add_website_resource_to_factsheet(self, fact_sheet_id, url, name, description=None):
        # Define the GraphQL mutation as a string
        graphql_mutation = gql('''
            mutation($factSheetId:ID!, $factSheetRev:Long, $name:String!, $description:String, $url:String, $origin:String, $documentType:String, $metadata:String, $refId:String){result:createDocument(factSheetId:$factSheetId, factSheetRev:$factSheetRev, name:$name, description:$description, url:$url, origin:$origin, documentType:$documentType, metadata:$metadata, refId:$refId){id name description url createdAt fileInformation{fileName size mediaType previewImage content}origin documentType metadata refId}}            
        ''')

        # Define the variables for the mutation
        variables = {
            "factSheetId": fact_sheet_id,
            "name": name,
            "description": description,
            "url": url,
            "origin": "CUSTOM_LINK",
            "documentType": "website",
            "metadata": None,
            "refId": None
        }

        
        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        response = client.execute(graphql_mutation, variable_values=variables)

        if 'errors' in response:
            print("Error occured while adding website resource")
            print(response)
            return None
        
        return True


    def upload_resource_to_factsheet(self, fact_sheet_id, file_path, document_name, document_type="documentation", description=None):
        # Define the GraphQL mutation as a string
        graphql_mutation = """
        mutation($factSheetId: ID!, $name: String!, $description: String, $url: String, $origin: String, $documentType: String, $metadata: String, $refId: String) {
            result: createDocument(factSheetId: $factSheetId, name: $name, description: $description, url: $url, origin: $origin, documentType: $documentType, metadata: $metadata, refId: $refId) {
                id
                name
                description
                url
                createdAt
                fileInformation {
                    fileName
                    size
                    mediaType
                    previewImage
                    content
                }
                origin
                documentType
                metadata
                refId
            }
        }
        """

        # Define the variables for the mutation
        variables = {
            "factSheetId": fact_sheet_id,
            "name": document_name,
            "description": description,
            "url": None,
            "origin": "LX_STORAGE_SERVICE",
            "documentType": document_type,
            "metadata": None,
            "refId": None
        }

        # Convert the GraphQL request to JSON
        graphQL_request = json.dumps({
            "query": graphql_mutation,
            "variables": variables
        })

        # Open the file in binary mode
        with open(file_path, 'rb') as file:
            # Prepare the multipart form-data payload
            files = {
                'file': (document_name, file, 'application/pdf'),
                'graphQLRequest': (None, graphQL_request, 'application/json')
            }

            # Make the POST request
            response = requests.post(self.upload_url, headers=self.header, files=files, verify=False)

        # Check for errors
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to upload resource. Status code: {response.status_code}")
            print(response.text)
            return None
        
            
    def get_resources_for_factsheet(self, fact_sheet_id):
        # GraphQL query to get documents attached to the factsheet
        graphql_query = """
        query($factSheetId: ID!) {
            factSheet(id: $factSheetId) {
                documents {
                    edges {
                        node {
                            id
                            name
                            documentType
                        }
                    }
                }
            }
        }
        """

        variables = {"factSheetId": fact_sheet_id}

        response = requests.post(self.request_url, json={"query": graphql_query, "variables": variables}, headers=self.header, verify=False)

        print(response.text)

        if response.status_code == 200:
            data = response.json()
            if 'errors' in data:
                print(f"GraphQL errors: {data['errors']}")
                return None
            edges = data['data']['factSheet']['documents']['edges']
            documents = [edge['node'] for edge in edges]
            return documents
        else:
            print(f"Failed to retrieve documents. Status code: {response.status_code}")
            print(response.text)
            return None
        
    def delete_resource(self, document_id):
        # GraphQL mutation to delete a document
        graphql_mutation = """
        mutation($id: ID!) {
            deleteDocument(id: $id) {
                id
            }
        }
        """

        variables = {"id": document_id}

        response = requests.post(
            self.request_url,
            json={"query": graphql_mutation, "variables": variables},
            headers=self.header,
            verify=False
        )

        print(response.text)

        if response.status_code == 200:
            data = response.json()
            if 'errors' in data:
                print(f"GraphQL errors: {data['errors']}")
                return None
            else:
                # Return the ID of the deleted document
                return True
        else:
            print(f"Failed to delete document. Status code: {response.status_code}")
            print(response.text)
            return None
        
    def update_costs(self, parent, factsheet_type, relationship_name, factsheet_id, costTotalAnnual, **kwargs):
        # Construct the value as a dictionary
        value_dict = {
            "costTotalAnnual": int(costTotalAnnual),
            "factSheetId": factsheet_id,
            "activeFrom": None,
            "activeUntil": None
        }

        other_fields = ""
        #walk through kwargs and append to other_items
        for key, value in kwargs.items():
            other_fields += f" {key}"

        # Add any other provided key-value pairs to value_dict
        value_dict.update(kwargs)

        if "factSheetId" not in value_dict:
            value_dict["factSheetId"] = factsheet_id

        # Find the relationship ID (the ID of the relationship itself) between the parent and the factsheet that records the cost
        target_relationship_id = None

        relationships = self.get_relationship_ids(parent, factsheet_type, relationship_name)
        for entry in relationships:
            if entry['to'] == factsheet_id:
                target_relationship_id = entry['relationship_id']
                break

        if not target_relationship_id:
            print(f"Cannot update costs. Relationship not found between {parent} and {factsheet_id}")
            return None


        # JSON-encode the value_dict to a string
        value_json_string = json.dumps(value_dict)

        json_data = {
            "query": "mutation($patches:[Patch]!){result:updateFactSheet(id:\"" + parent + "\", patches:$patches, validateOnly:false){factSheet{id rev completion{percentage sectionCompletions{name percentage subSectionCompletions{name percentage}}}... on " + factsheet_type + "{" + relationship_name + "{permissions{self create read update delete}edges{node{id activeFrom activeUntil costTotalAnnual " + other_fields + " factSheet{id displayName fullName description type category subscriptions{edges{node{id type user{id displayName technicalUser email}}}}...on ITComponent{ITComponentLifecycle:lifecycle{asString phases{phase startDate}}}...on Application{lxHostingType}tags{id name description color tagGroup{id shortName name}}}}}}}}}}",
            "variables": {
                "patches": [
                    {
                        "op": "replace",
                        "path": "/" + relationship_name + "/" + target_relationship_id, 
                        "value": value_json_string  # Pass the JSON-encoded string here
                    }
                ]
            }
        }

        response = requests.post(self.request_url, headers=self.header, json=json_data, verify=False)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to update costs. Status code: {response.status_code}")
            print(response.text)
            return None




    def delete_contracts_with_coupa_tag(self):
        self.delete_contracts_with_tag(self._coupa_tag)
    
    
    def delete_contracts_with_tag(self,theTag):
        """Delete all contract factsheets that have the 'Coupa' tag."""
        if not self._coupa_tag:
            raise Exception("Coupa tag ID is not available. Ensure it is set during initialization.")

        # Define the GraphQL query to fetch the contracts with the Coupa tag
        query = gql("""
        query allFactSheetsQuery($filter: FilterInput!, $sortings: [Sorting]) {
            allFactSheets(filter: $filter, sort: $sortings) {
                totalCount
                edges {
                    node {
                        ... on Contract {
                            id
                            permissions {
                                create
                                read
                                update
                                delete
                                self
                            }
                        }
                    }
                }
            }
        }
        """)

        variables = {
            "filter": {
                "responseOptions": {
                    "maxFacetDepth": 5
                },
                "facetFilters": [
                    {
                        "facetKey": "_TAGS_",
                        "operator": "OR",
                        "keys": [
                            theTag
                        ]
                    },
                    {
                        "facetKey": "FactSheetTypes",
                        "operator": "OR",
                        "keys": [
                            "Contract"
                        ]
                    }
                ]
            },
            "sortings": [
                {
                    "key": "displayName",
                    "order": "asc"
                }
            ]
        }

        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        response = client.execute(query, variable_values=variables)

        if 'allFactSheets' not in response or 'edges' not in response['allFactSheets']:
            raise Exception(f"Unexpected response structure: {response}")

        contracts_to_delete = [
            edge['node']['id'] for edge in response['allFactSheets']['edges']
        ]

        print(contracts_to_delete)

        if not contracts_to_delete:
            print("No contracts found with the 'Coupa' tag.")
            return

        # Delete each contract
        for contract_id in contracts_to_delete:
            self.archive_factsheet(contract_id)

        print(f"Completed deletion process. Total contracts deleted: {len(contracts_to_delete)}")

    
    def delete_factsheets_with_tag(self, factsheetType, theTag):
        """Delete all contract factsheets that have the 'Coupa' tag."""
        if not self._coupa_tag:
            raise Exception("Coupa tag ID is not available. Ensure it is set during initialization.")

        # Define the GraphQL query to fetch the contracts with the Coupa tag
        query = gql("""
        query allFactSheetsQuery($filter: FilterInput!, $sortings: [Sorting]) {
            allFactSheets(filter: $filter, sort: $sortings) {
                totalCount
                edges {
                    node {
                        ... on %s {
                            id
                            permissions {
                                create
                                read
                                update
                                delete
                                self
                            }
                        }
                    }
                }
            }
        }
        """ % (factsheetType))

        variables = {
            "filter": {
                "responseOptions": {
                    "maxFacetDepth": 5
                },
                "facetFilters": [
                    {
                        "facetKey": "_TAGS_",
                        "operator": "OR",
                        "keys": [
                            theTag
                        ]
                    },
                    {
                        "facetKey": "FactSheetTypes",
                        "operator": "OR",
                        "keys": [
                            factsheetType
                        ]
                    }
                ]
            },
            "sortings": [
                {
                    "key": "displayName",
                    "order": "asc"
                }
            ]
        }

        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        response = client.execute(query, variable_values=variables)

        if 'allFactSheets' not in response or 'edges' not in response['allFactSheets']:
            raise Exception(f"Unexpected response structure: {response}")

        contracts_to_delete = [
            edge['node']['id'] for edge in response['allFactSheets']['edges']
        ]

        print(contracts_to_delete)

        if not contracts_to_delete:
            print("No factsheets found with the tag.")
            return

        # Delete each contract
        for contract_id in contracts_to_delete:
            self.archive_factsheet(contract_id)

        print(f"Completed deletion process. Total factsheets deleted: {len(contracts_to_delete)}")

    
        
        
    def get_factsheet_revision(self, factsheet_id):
        """Fetch the current revision number of the factsheet."""
        query = gql("""
        query {
            factSheet(id: "%s") {
                id
                rev
            }
        }
        """ % factsheet_id)

        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        response = client.execute(query)
        return response['factSheet']['rev']

    def archive_factsheet(self, factsheet_id):
        """Archive a factsheet by setting its status to 'ARCHIVED'."""

        # Get the current revision number of the factsheet
        current_revision = self.get_factsheet_revision(factsheet_id)

        # Define the GraphQL mutation to archive the factsheet
        archive_mutation = gql("""
        mutation($comment: String!, $patches: [Patch]!) {
            result: updateFactSheet(
                id: "%s", 
                rev: %d, 
                comment: $comment, 
                patches: $patches, 
                validateOnly: false
            ) {
                factSheet {
                    id
                    name
                    status
                }
            }
        }
        """ % (factsheet_id, current_revision))

        # Define the variables for the mutation
        variables = {
            "comment": "Archiving the factsheet",
            "patches": [
                {
                    "op": "add",
                    "path": "/status",
                    "value": "ARCHIVED"
                }
            ]
        }

        # Execute the mutation using the LeanIX API client
        transport = RequestsHTTPTransport(
            url=self.request_url,
            headers=self.header,
            use_json=True,
            verify=False
        )

        client = Client(transport=transport, fetch_schema_from_transport=True)

        response = client.execute(archive_mutation, variable_values=variables)

        if 'result' in response and response['result']:
            print(f"Archived factsheet: ID: {factsheet_id}")
        else:
            print(f"Failed to archive factsheet: ID: {factsheet_id}")



    def get_schemas(self, factsheet_id):
        """
        Retrieve the metric schema for the given factsheet.
        """
        url = self.metrics_url #+ factsheet_id
        response = requests.get(url, headers=self.header)
        print(url)
        print(response.text)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None  # No schema exists yet
        else:
            raise Exception(f"Failed to retrieve schema: {response.status_code}, {response.text}")



    def create_metric_schema(self, schema_name, attributes, description):
        """
        Create a new schema for the given factsheet if it doesn't exist.

        Usage:

        attributes = [
            {"name": "factSheetId", "type": "dimension"},
            {"name": "seriesType", "type": "dimension"},
            {"name": "resourceGroup", "type": "dimension"},
            {"name": "value", "type": "metric"},                
        ]

        #This returns the Guid:
        print(leanix_api.create_metric_schema("dataUpload", attributes, "User Traffic (upload)"))

        """

        # attributes = [{"name": key, "type": "metric"} for key in labels] + [{"name": "factSheetId", "type": "dimension"}]
        schema = {
            "name": schema_name,
            "description": description,
            "attributes": attributes
        }

        url = self.metrics_url + f"/services/metrics/v2/schemas"

        response = requests.post(url, headers=self.header, json=schema)
        print(response)
        if response.status_code == 201 or response.status_code == 200:
            return response.json()["uuid"]
        else:
            raise Exception(f"Failed to create schema: {response.status_code}, {response.text}")

    def metric_add_chart(self, chartId, chart_title, series_names):
        """
        Generate a chart with the given chart title and series names.
        
        Args:
            chart_title (str): The title of the chart.
            series_names (list): A list of dictionaries containing series names and other related parameters for the chart.
        """
        url = self.metrics_url + f"/services/metrics/v2/charts"
        
        # Define the payload with the series and chart title
        payload ={
                "id": chartId,
                "chart": {
                    "title": chart_title,
                    "chartProduct": None,
                    "config": {
                        "timespan": "52w",
                        "titleYAxis": "Cost",
                        "chartType": None,
                        "defaultAggregation": "month",
                        "aggregationTypes": [
                            "month",
                            "year",
                            "quarter"
                        ],
                        "missingDataConfiguration": "SHOW_GAP"
                    },
                    "forReporting": False,
                    "isStacked": True
                },
                "series": []
            }
        
        
        # Add each series from series_names to the payload
        for index, series in enumerate(series_names):
            series_data = {
                "title": series.get("title", f"Series{index + 1}"),
                "measurement": series.get("measurement", "leanixV4FactSheetCounts"),
                "fieldName": "value",
                "type": "area",
                "tagsRule": {
                    "operator": "AND",
                    "rules": [
                        {
                            "tagName": "factSheetId",
                            "operator": "equals",
                            "target": "factSheetId"
                        }
                    ]
                },
                "aggregationFunction": "SUM",
                "grouping": "1d",
                "color": series.get("color", "#DA4F49"),
                "unit": "EUR",
                "inventoryLink": None
            }
            payload["series"].append(series_data)

        print(json.dumps(payload, indent=3))

        # Send the POST request to the LeanIX API
        response = requests.post(url, headers=self.header, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to generate chart: {response.status_code} - {response.text}")




    def metric_add_timeseries_data(self, factsheet_id, schema_uuid, timeseries_data):
        """
        Add timeseries data to the factsheet.
        """
        url = self.metrics_url + f"/services/metrics/v2/schemas/{schema_uuid}/points"

        payload = []
        for row in timeseries_data:            
            data = {
                "timestamp": row['date'] + "T00:00:00.000Z",
                # "date": row['date'] + "T00:00:00.000Z",
                "factSheetId": factsheet_id,
                "seriesType": row["seriesType"],
                "resourceGroup": row["resourceGroup"],
                "value": round(float(row["value"]), 2)         
            }

            dt = datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
            data["timestamp"] = dt.timestamp()


            """
            {
            "timestamp": "2024-09-21T13:28:27.487800+00:00",
            "date": 1726869600, 
            "factSheetId": "f86a78a1-2109-449c-af5a-3ce7d843a05d",
            "value": 26943.94
            }
            
            """

            print(data)

            #exclude factSheetID from data
            response = requests.post(url, headers=self.header, json=data)


            print(response.text)



            payload.append(data)


        # response = requests.post(url, headers=self.header, json=payload)

        print(response.text)

        if response.status_code == 200:
            print("OK")
            return response.json()
        else:
            raise Exception(f"Failed to add timeseries data: {response.status_code}, {response.text}")
        
    def get_discovery_utilization(self, discoverySource, linkedApps):
        # last_7days = datetime.now(timezone.utc) - timedelta(days=7)
        # last_7days_str = last_7days.strftime("%Y-%m-%dT00:00:00Z")

        last_1days = datetime.now(timezone.utc) - timedelta(days=1)
        last_1days_str = last_1days.strftime("%Y-%m-%dT00:00:00Z")

        # first download big report
        data_url = f"{self.metrics_url}services/discovery-saas/v1/discoveries?cursor={last_1days_str}"
        response = self._call_generic(data_url, "GET")

        results = {}

        for app in response['data']:
            #validate the right discovery source is used (i.e. not Entra)
            if 'source' in app:
                if 'type' in app['source']:
                    if app['source']['type'] != discoverySource:
                        continue

            if app['catalogID'] in linkedApps:
                factsheetId = linkedApps[app['catalogID']]
                results[factsheetId] = {}
                
                for detail in app['discoveryDetails']:                    
                    results[factsheetId][detail['key']] = detail['value']                    

        return results




    def get_discovery_linked_apps(self, sourceConfigID):
        url = f"{self.metrics_url}services/discovery-linking/v1/discovery-items"
        page_number = 0
        page_size = 50
        all_mappings = {}

        while True:
            data = []
            rows = []

            body = {
                "pagination": {
                    "pageSize": page_size,
                    "pageNumber": page_number
                },
                "filter": {
                    "origin": ["discovery_saas"],
                    "linkingStatus": ["linked"],
                    "sourceConfigID": [sourceConfigID]
                }
            }

            
            data = self._call_generic(url, "POST", payload=body)

            rows = data.get("rows", [])
            if not rows or len(rows) == 0:
                break

            for item in rows:
                if "catalogEntry" in item:
                    if item["catalogEntry"] is not None:
                        if "catalogID" in item["catalogEntry"]:
                            catalogID = item.get("catalogEntry", {}).get("catalogID")
                            links = item.get("links", [])
                            if links is not None:
                                for link in links:
                                    factSheetId = link.get("factSheetId")
                                    if catalogID and factSheetId:
                                        all_mappings[catalogID] = factSheetId


            page_number += 1

        return all_mappings


