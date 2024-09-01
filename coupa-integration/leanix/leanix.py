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

    def __init__(self, api_token, auth_url, request_url):
        self.api_token = api_token
        self.auth_url = auth_url
        self.request_url = request_url
        self.header = self._authenticate()

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
    def _call(self, query, dump=True):
        data = {"query": query}

        if dump:
            json_data = json.dumps(data)
        else:
            json_data = data


        try:
            # print(json_data)  # For debugging purposes
            response = requests.post(url=self.request_url, headers=self.header, data=json_data, verify=False, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if response:
                #check if error is a 401
                if response.status_code == 401:
                    print("Unauthorized. Re-authenticating...")
                    self.header = self._authenticate()
                    return self._call(query, dump)
            
            print(f"Request failed: {e}")
            raise
        
        return response.json()

    def create_factsheet(self, type, name, subtype=None):
        # Define the mutation with or without the subtype based on its presence
        if subtype:
            query = """
            mutation {
                createFactSheet(input: {name: "%s", type: %s, category: "%s"}) {
                    factSheet {
                        id
                    }
                }
            }
            """ % (name, type, subtype)
            print("Create " + type + " with subtype " + subtype + ": " + name)
        else:
            query = """
            mutation {
                createFactSheet(input: {name: "%s", type: %s}) {
                    factSheet {
                        id                        
                    }
                }
            }
            """ % (name, type)
            print("Create " + type + ": " + name)

        # Execute the mutation
        response = self._call(query)

        # handle error
        if 'errors' in response:
            print(response)
            return None
        
        #handle if no data is returned
        if 'data' not in response:
            print(response.text)
            return None

        return response['data']['createFactSheet']['factSheet']['id']

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




    def get_all(self, type):
        query = """
        {
            allFactSheets(filter: {facetFilters: [{facetKey: "FactSheetTypes", keys: ["%s"]}]}) {
                edges {
                    node {
                        id
                        name

                        ...on Application{
                            alias
                        }
                    }
                }
            }
        }
        """ % type

        response = self._call(query)

        # Collect all applications with their ids
        applications = []


        for edge in response['data']['allFactSheets']['edges']:
            applications.append({
                'id': edge['node']['id'],
                'name': edge['node']['name'],
            })

            if 'alias' in edge['node']:
                if edge['node']['alias'] != "":
                    applications[-1]['alias'] = edge['node']['alias']
            else:
                applications[-1]['alias'] = None
        
        return applications

    def create_it_component(self, name):
        return self.create_factsheet("ITComponent", name)
    
    def create_application(self, name):
        return self.create_factsheet("Application", name)
    
    
    def create_contract(self, supplierName, name, description, subtype="Contract", isActive=True, isExpired=False, contractValue=0, numberOfSeats=None, volumeType="License", phasein_date=None, active_date=None, notice_date=None, eol_date=None, externalId="", externalUrl="", applicationId="", domains=[], managedByName=None, managedByEmail=None, currency="EUR"):
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
        
        print(externalStr)

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


    def create_relation_with_costs(self, app_id, itc_id, costs):
        query = """
        mutation {
            updateFactSheet(id: "%s", 
                            patches: [{op: add, path: "/relITComponentToApplication/new_1", 
                                       value: "{\\\"factSheetId\\\": \\\"%s\\\",\\\"costTotalAnnual\\\": %s}"}]) {
                factSheet {
                    id
                }
            }
        }
        """ % (itc_id, app_id, costs)
        print("Create relation with costs: " + itc_id + "->" + app_id + " = " + str(costs))
        self._call(query)

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
        

    
    
    
    
    def delete_contracts_with_coupa_tag(self):
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
                            self._coupa_tag
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
