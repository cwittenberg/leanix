import time
import json
import requests
import warnings
from urllib3.exceptions import InsecureRequestWarning
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging
import os
import sys

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Disable InsecureRequestWarnings if needed
warnings.simplefilter('ignore', InsecureRequestWarning)

from datetime import datetime, timedelta

class SubcomponentGraph:
    auth_url = "https://login.microsoftonline.com/<tenant_id>/oauth2/v2.0/token"
    cost_management_url = "https://management.azure.com/providers/Microsoft.Management/managementGroups/anmgsecurity/providers/Microsoft.CostManagement/query?api-version=2021-10-01&$top=5000"

    subscription_tenant_sizes = "c8303ec8-7fcb-4228-b23a-a90ab6ee869a" #use just a (random) example of a subscription here, used to get tenant VM sizes
    azure_location = "westeurope"

    def __init__(self, tenant_id, client_id, client_secret):
        self.auth_url = self.auth_url.replace("<tenant_id>", tenant_id)
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = self._authenticate(client_id, client_secret)
        self.header = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def _authenticate(self, client_id, client_secret):
        # Create the form-encoded data payload
        data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://management.azure.com/.default'
        }
        
        # Send the POST request to get the token
        response = requests.post(self.auth_url, data=data)
        
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()  # Return the JSON response (contains the access token)
            return data['access_token']
        else:
            # Raise an error if something went wrong
            raise Exception(f"Failed to retrieve token: {response.status_code}, {response.text}")

    @retry(
        stop=stop_after_attempt(3),  # Stop after 3 attempts
        wait=wait_exponential(multiplier=1, min=2, max=60),  # Exponential backoff: wait 2^x * 1 (where x is the attempt number)
        retry=retry_if_exception_type(requests.exceptions.RequestException),  # Retry on any requests exceptions
        before_sleep=before_sleep_log(logger, logging.INFO)  # Log before retrying
    )
    def _call(self, url, json_payload={}, method="POST"):
        try:

            if method == "GET":
                response = requests.get(url, headers=self.header, verify=False, timeout=10)
            else:
                # Send the POST request to the provided URL with the payload
                response = requests.post(url, headers=self.header, json=json_payload, verify=False, timeout=10)
            
            response.raise_for_status()  # Raise an error for bad status codes (4xx, 5xx)
            
        except requests.exceptions.RequestException as e:
            if response and response.status_code == 401:
                print("Unauthorized. Re-authenticating...")
                self.token = self._authenticate(self.client_id, self.client_secret)
                self.header['Authorization'] = f'Bearer {self.token}'
                return self._call(url, json_payload)  # Retry the call after re-authentication
        except:
            if response and response.status_code == 429:
                print("Rate limited. Retrying...")
                time.sleep(3)
                return self._call(url, json_payload)  # Retry the call after waiting
            
            print(f"Request failed: {e}")
            raise
        
        return response.json()


    def get_costs_by_service_name(self, service_name, from_date=None, to_date=None):
        if not from_date:
            # Default to one year ago
            from_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        if not to_date:
            # Default to today
            to_date = datetime.now().strftime('%Y-%m-%d')

        # Define the payload for the cost management API with updated structure
        payload = {
            "type": "ActualCost",
            "dataSet": {
                "granularity": "Monthly",  # Updated to Monthly granularity
                "aggregation": {
                    "totalCost": {
                        "name": "Cost",
                        "function": "Sum"
                    },
                    "totalCostUSD": {
                        "name": "CostUSD",
                        "function": "Sum"
                    }
                },
                "sorting": [
                    {
                        "direction": "ascending",  # Sorting by BillingMonth in ascending order
                        "name": "BillingMonth"
                    }
                ],
                "grouping": [
                    {
                        "type": "Dimension",
                        "name": "ServiceName"
                    },
                    {
                        "type": "Dimension",
                        "name": "SubscriptionId"
                    },
                    {
                        "type": "Dimension",
                        "name": "ResourceLocation"
                    }
                ],
                "filter": {
                    "Dimensions": {
                        "Name": "ServiceName",
                        "Operator": "In",
                        "Values": [
                            service_name  # The service name passed to the function
                        ]
                    }
                }
            },
            "timeframe": "Custom",
            "timePeriod": {
                "from": from_date + "T00:00:00+00:00",  # Time range start
                "to": to_date + "T23:59:59+00:00"  # Time range end
            }
        }

        # Make the API call to get the costs
        result = self._call(self.cost_management_url, payload)

        return result['properties']['rows']
    
    def get_costs_by_apm_id(self, apm_id, from_date=None, to_date=None):
        if not from_date:
            # Default to one year ago
            from_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        if not to_date:
            # Default to today
            to_date = datetime.now().strftime('%Y-%m-%d')

        # Define the payload for the cost management API with updated structure
        payload = {
            "type": "ActualCost",
            "dataSet": {
                "granularity": "Yearly",  # Updated to Monthly granularity
                "aggregation": {
                    "totalCost": {
                        "name": "Cost",
                        "function": "Sum"
                    },
                    "totalCostUSD": {
                        "name": "CostUSD",
                        "function": "Sum"
                    }
                },
                "sorting": [
                    {
                        "direction": "ascending",  # Sorting by BillingMonth in ascending order
                        "name": "BillingMonth"
                    }
                ],
                "grouping": [
                    {
                        "type": "Dimension",
                        "name": "ServiceName"
                    },
                    {
                        "type": "Dimension",
                        "name": "ResourceGroupName"
                    },                    
                    {
                        "type": "Dimension",
                        "name": "ResourceLocation"
                    },
                    {
                        "type": "Dimension",
                        "name": "SubscriptionId"
                    }
                ],
                "filter": {
                    "Tags": {
                        "Name": "ApplicationId",
                        "Operator": "In",
                        "Values": [
                            apm_id  # The service name passed to the function
                        ]
                    }
                }
            },
            "timeframe": "Custom",
            "timePeriod": {
                "from": from_date + "T00:00:00+00:00",  # Time range start
                "to": to_date + "T23:59:59+00:00"  # Time range end
            }
        }

        # Make the API call to get the costs
        result = self._call(self.cost_management_url, payload)
    
        if "properties" in result and "rows" in result['properties']:
            result = result['properties']['rows']
        else:
            print("Error occurred in retrieving costs")
            print(result)
            if result['error']['code'] == '429':
                print("Rate limited. Retrying...")
                time.sleep(3)
                return self.get_costs_by_apm_id(apm_id, from_date, to_date)

        response = {}

        for item in result:
            cost = item[0] #in eur
            service = item[2]
            resource_group = item[3]            
            resource_location = item[4]
            subscriptionId = item[5]

            environment = "Unknown"

            if resource_group.lower().startswith('p'):
                environment = 'Production'
            elif resource_group.lower().startswith('t'):
                environment = 'Test'
            elif resource_group.lower().startswith('d'):
                environment = 'Development'
            elif resource_group.lower().startswith('a'):
                environment = 'Acceptance'            
            else:
                pass

            rgName = f"{environment} ({resource_group})"

            if rgName not in response:
                response[rgName] = []

            item = {
                "service": service,
                "cost_yearly_eur": cost,     
                "resource_group": resource_group, 
                "subscription_id": subscriptionId,
                "resource_location": resource_location,
                "environment": environment
            }            

            if service == "Virtual Machines Licenses" and cost == 0:
                continue

            if service == "Virtual Machines":
                item['vms'] = self.get_resource_graph(apm_id, resource_group)
        
            response[rgName].append(item)

        return response
        
                    
           

    
    def get_vm_configurations(self):
        url = f"https://management.azure.com/subscriptions/{self.subscription_tenant_sizes}/providers/Microsoft.Compute/locations/{self.azure_location}/vmSizes?api-version=2022-08-01"

        result = self._call(url, method="GET")
    
        response = {}
        for vm in result['value']:
            response[vm['name']] = vm
            vm['osDiskSizeInGB'] = vm['osDiskSizeInMB'] / 1024
            vm['resourceDiskSizeInGB'] = vm['resourceDiskSizeInMB'] / 1024

            del vm['osDiskSizeInMB']
            del vm['resourceDiskSizeInMB']

        return response

    def get_resource_graph(self, apm_id, resource_group):
        resource_query = f"""
ResourceContainers
| where type == "microsoft.resources/subscriptions/resourcegroups"
| extend applicationId = coalesce(
    tostring(tags['ApplicationId']),
    tostring(tags['ApplicationID']),
    tostring(tags['applicationid'])
)
| extend service_id = subscriptionId
| where applicationId == "{apm_id}"
| project resourceGroupName = name, applicationId, service_id
| where resourceGroupName == "{resource_group}"
| join kind=inner (
    Resources
    | extend resourceId = id
    | extend tags = tags
    | extend vmSize = tostring(properties.hardwareProfile.vmSize)
    | extend vmStatus = tostring(properties.extended.instanceView.powerState.displayStatus)
    | extend vmHostname = tostring(properties.osProfile.computerName)
    | extend os_type = tostring(properties.storageProfile.osDisk.osType)
    | extend os = tostring(properties.extended.instanceView.osName)
    | extend os_version = tostring(properties.extended.instanceView.osVersion)
    // Expand data disks and retrieve their sizes
    | extend dataDisks = properties.storageProfile.dataDisks
    | mv-expand dataDisks to typeof(dynamic)
    | extend diskSizeGB = iif(
        type == 'microsoft.compute/disks',
        toint(properties['diskSizeGB']),
        toint(dataDisks['diskSizeGB'])
    )
    // Access managedDiskId
    | extend managedDiskId = tostring(dataDisks.managedDisk.id)
    // Extract vCPU count from vmSize
    | extend vCPU = toint(extract(".+[A-Z]([0-9]+).+", 1, vmSize))
    // Extract network interface IDs
    | extend networkInterfaceIds = properties.networkProfile.networkInterfaces
    | mv-expand networkInterfaceIds
    | extend networkInterfaceId = tostring(networkInterfaceIds.id)
    | project location, resourceId, name, resourceType = type, vmHostname, vmSize, vCPU, vmStatus, diskSizeGB, resourceGroup, managedDiskId, os_type, os, os_version, networkInterfaceId, tags
) on $left.resourceGroupName == $right.resourceGroup
| join kind=leftouter (
    Resources
    | where type =~ 'Microsoft.Network/networkInterfaces'
    | extend nicId = id
    | extend ipConfigs = properties.ipConfigurations
    | mv-expand ipConfigs to typeof(dynamic)
    | extend privateIPAddress = tostring(ipConfigs.properties.privateIPAddress)
    // Retrieve subnet and virtual network information
    | extend subnetId = tostring(ipConfigs.properties.subnet.id)
    | extend vnet = tostring(extract('.*?/virtualNetworks/([^/]+)', 1, subnetId))
    | extend subnet = tostring(extract('.*?/subnets/([^/]+)', 1, subnetId))
    // Format vnet/subnet pair
    | extend vnetSubnetPair = strcat(vnet, "/", subnet)
    | summarize privateIPAddresses = make_list(privateIPAddress), vnetSubnetPairs = make_list(vnetSubnetPair) by nicId
) on $left.networkInterfaceId == $right.nicId
| project location, resourceId, name, resourceType, vmHostname, vmSize, vCPU, vmStatus, diskSizeGB, resourceGroup, service_id, applicationId, managedDiskId, os_type, os, os_version, privateIPAddresses, vnetSubnetPairs, tags
        """

        payload = {
            "query": resource_query
        }

        result = self._call("https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01", payload)
        data = result['data']

        diskData = {}

        vm_configurations = self.get_vm_configurations()

        vms = {}

        response = []
        for row in data:   
            if row['resourceGroup'] != resource_group:
                continue#######THIS IS NOT WORKING APPARENTLY. STILL HAVE DEV WHERE I DONT WANT IT

            if row['resourceGroup'].lower().startswith('p'):
                row['environment'] = 'Production'
            elif row['resourceGroup'].lower().startswith('t'):
                row['environment'] = 'Test'
            elif row['resourceGroup'].lower().startswith('d'):
                row['environment'] = 'Development'
            else:
                row['environment'] = 'Unknown'
            
            if row['resourceType'] == 'microsoft.compute/disks':
                if row['resourceId'] not in diskData:
                    diskData[row['resourceId']] = 0                    

                diskData[row['resourceId']] += row['diskSizeGB']
            
            elif row['resourceType'] == 'microsoft.compute/virtualmachines/extensions' or \
                    row['resourceType'] == 'microsoft.network/networkinterfaces' or \
                        row['resourceType'] == 'microsoft.storage/storageaccounts' or \
                            row['resourceType'] == 'microsoft.sqlvirtualmachine/sqlvirtualmachines':
                pass

            elif row['resourceType'] == 'microsoft.compute/virtualmachines':
                if row['resourceId'] in vms:
                    vms[row['resourceId']]['diskSizeGB'] + row['diskSizeGB'] 
                else:
                    vms[row['resourceId']] = row

                if 'managedDiskId' in row:
                    if row['managedDiskId'] in diskData:
                        vms[row['resourceId']]['diskSizeGB'] += diskData[row['managedDiskId']] 

                        if not 'managedDisks' in vms[row['resourceId']]:
                            vms[row['resourceId']]['managedDisks'] = []

                        vms[row['resourceId']]['managedDisks'].append(row['managedDiskId'])

                        # del vms[row['resourceId']]

                if row['vmSize'] in vm_configurations:
                    vms[row['resourceId']].update(vm_configurations[row['vmSize']])

            else:
                # response.append(row)
                pass

            
        response.extend(vms.values())

        return response


        
