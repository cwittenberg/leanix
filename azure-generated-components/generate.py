import os
import sys
import re
import json
import pprint

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

# Import my LeanIX API class
from leanix.leanix import LeanIXAPI
from azurecosts.azuregraph import Azuregraph

azure_tenant_id = "<tenant id>"
azure_client_id = "<client id>"
azure_client_secret = "<secret>"

azureProviderId = "<microsoft provider Guid in leanix>"

az = Azuregraph(azure_tenant_id, azure_client_id, azure_client_secret)

leanix_token = '<leanix token>'
leanix_base_url = 'https://<tenant>.leanix.net/' 
leanix_auth_url = leanix_base_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_base_url + 'AkzoNobelLive/factsheet/'
leanix_metrics_url = leanix_base_url
leanix_request_url = leanix_base_url + 'services/pathfinder/v1/graphql'

leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url, leanix_metrics_url, search_base_url=leanix_base_url)

AZURE_TAG = "<tag guid of AZURE tag in leanix>" #tag defined in LeanIX for Azure resources, created it if you don't have it.

def azureToLeanIX(leanix_api, apm_id):
    global AZURE_TAG

    print("Retrieving Azure graph and costs for APM ID: " + apm_id)
    azureResult = az.get_costs_by_apm_id( apm_id )

    print("Done. Now parsing and adding to LeanIX")

    for apm_result in leanix_api.search( apm_id ):

        if apm_result['type'] == 'Application' and 'externalId' in apm_result:
            app_id = apm_result['id']
            
            if app_id is not None:
                ##################################################
                # Get IT component structure of APM ID in LeanIX #
                ##################################################

                components = leanix_api.get_relationships(app_id, "Application", "relApplicationToITComponent")

                azureHostingComponent = None #main component ID for Azure SaaS Hosting
                azureHostingExists = False

                for component in components:
                    if component['name'] == "Azure Hosting - " + apm_id:
                        azureHostingExists = True
                        azureHostingComponent = component['id']
                        break
                

                if not azureHostingExists:
                    azureHostingComponent = leanix_api.create_factsheet("ITComponent", "Azure Hosting - " + apm_id, "hardware")                
                    
                    patches = [
                        {
                            "op": "add",
                            "path": "/tags",
                            "value": '[{"tagId":"' + AZURE_TAG + '"}]'
                        },
                        {
                            "op": "add",
                            "path": "/relITComponentToApplication/new_1",
                            "value": '{"factSheetId":"' + app_id + '"}'
                        }
                    ]

                    leanix_api.modify_factsheet(azureHostingComponent, patches)

                    azureHostingExists = True

                # rgToFactsheet = {}

                totalRGCost = {}

                #############################################################
                # Add each resourcegroup as a component under Azure Hosting #
                #############################################################
                for rgName in azureResult:
                    rgComponent = leanix_api.create_factsheet("ITComponent", rgName, "hardware")

                    totalRGCost[rgComponent] = 0

                    patches = [
                        {
                            "op": "add",
                            "path": "/tags",
                            "value": '[{"tagId":"' + AZURE_TAG + '"}]'
                        },
                        {
                            "op": "add",
                            "path": "/relSubcomponentITComponentToParentalComponentITComponent/new_" + rgComponent,
                            "value": '{"factSheetId":"' + azureHostingComponent + '"}'
                        }
                    ]

                    leanix_api.modify_factsheet(rgComponent, patches)

                    for resource in azureResult[rgName]:
                        print(resource)
                        serviceName = resource['service']

                        resourceComponent = leanix_api.create_factsheet("ITComponent", serviceName, "paas")

                        patches = [
                            {
                                "op": "add",
                                "path": "/tags",
                                "value": '[{"tagId":"' + AZURE_TAG + '"}]'
                            },
                            {
                                "op": "add",
                                "path": "/relITComponentToProvider/new_provider" + resourceComponent,
                                "value": '{"factSheetId":"' + azureProviderId + '"}'
                            },
                            {
                                "op": "add",
                                "path": "/relSubcomponentITComponentToParentalComponentITComponent/new_subcomponent" + resourceComponent,
                                "value": '{"factSheetId":"' + rgComponent + '"}'
                            },                        
                        ]

                        try:
                            leanix_api.modify_factsheet(resourceComponent, patches)

                        except Exception as e:
                            #get message
                            if str(e).find("'errorType': 'UNIQUE'") > -1:
                                print("Resource already exists with this Provider allocated")

                                archivedResource = resourceComponent

                                #delete the new resource and repoint to the existing
                                leanix_api.archive_factsheet(resourceComponent)

                                resourceComponent = None

                                existing = leanix_api.search(serviceName)
                                for e in existing:
                                    if e['id'] != archivedResource:
                                        if e['name'].lower() == serviceName.lower() or \
                                            e['name'].lower() == f"microsoft / azure {serviceName.lower()}" or \
                                                e['name'].lower() == f"azure {serviceName.lower()}" or \
                                                    e['name'].lower() == f"microsoft {serviceName.lower()}":
                                            resourceComponent = e['id']
                                            break

                                if resourceComponent is not None:
                                    print("Existing component found for " + serviceName + " with id " + resourceComponent)
                                    #modify again, but then minus the provider relation, and minus the Azure tag (so it doesnt get deleted - when I delete by all tags)
                                    patches = [
                                        {
                                            "op": "add",
                                            "path": "/relSubcomponentITComponentToParentalComponentITComponent/new_subcomponent" + resourceComponent,
                                            "value": '{"factSheetId":"' + rgComponent + '"}'
                                        },                        
                                    ]
                                    leanix_api.modify_factsheet(resourceComponent, patches)
                                else:
                                    print("** ERROR! Resource not found in LeanIX: " + serviceName)
                                    continue
                            else:
                                print("Error: " + str(e))
                                exit(-1)


                        leanix_api.update_costs(
                            parent = rgComponent,\
                            factsheet_type = "ITComponent", \
                            relationship_name = "relParentalComponentITComponentToSubcomponentITComponent", \
                            factsheet_id = resourceComponent,
                            costTotalAnnual = resource['cost_yearly_eur'],
                            resource_location = resource['resource_location']
                        )

                        totalRGCost[rgComponent] += resource['cost_yearly_eur']

                        if serviceName == "Virtual Machines":
                            ####################################################################
                            # Add VMs underneath this resource, as part of this resource group #
                            ####################################################################

                            for vm in resource['vms']:
                                vmName = "VM " + vm['resourceId'].split("/")[-1]

                                vmComponent = leanix_api.create_factsheet("ITComponent", vmName, "hardware")

                                ramAllocated = 0

                                # check if memoryInMB is a number
                                #
                                if vm['memoryInMB'] > 0:
                                    ramAllocated = vm['memoryInMB']
                                    ramAllocated = int(ramAllocated / 1024)
                                    if ramAllocated < 0:
                                        ramAllocated = 0
                                else:
                                    # if not, try to convert it to a number
                                    try:
                                        ramAllocated = int(int(vm['memoryInMB']) / 1024)
                                        if ramAllocated < 0:
                                            ramAllocated = 0
                                    except ValueError:
                                        # if it's not a number, set it to 0
                                        ramAllocated = 0


                                diskOSSize = 0

                                # check if osDiskSizeInMB is a number
                                #
                                if vm['osDiskSizeInGB'] > 0:
                                    diskOSSize = vm['osDiskSizeInGB']
                                    diskOSSize = int(diskOSSize)
                                    if diskOSSize < 0:
                                        diskOSSize = 0
                                else:
                                    # if not, try to convert it to a number
                                    try:
                                        diskOSSize = int(vm['osDiskSizeInGB'])
                                        if diskOSSize < 0:
                                            diskOSSize = 0
                                    except ValueError:
                                        # if it's not a number, set it to 0
                                        diskOSSize = 0

                                diskSizeGB = 0

                                # check if diskSizeGB is a number
                                #
                                if vm['diskSizeGB'] > 0:
                                    diskSizeGB = vm['diskSizeGB']
                                    diskSizeGB = int(diskSizeGB)
                                    if diskSizeGB < 0:
                                        diskSizeGB = 0
                                else:
                                    # if not, try to convert it to a number
                                    try:
                                        diskSizeGB = int(vm['diskSizeGB'])
                                        if diskSizeGB < 0:
                                            diskSizeGB = 0
                                    except ValueError:
                                        # if it's not a number, set it to 0
                                        diskSizeGB = 0


                                patches = [
                                    {
                                        "op": "add",
                                        "path": "/tags",
                                        "value": '[{"tagId":"' + AZURE_TAG + '"}]'
                                    },
                                    # {
                                    #     "op": "add",
                                    #     "path": "/relITComponentToProvider/new_provider" + vmComponent,
                                    #     "value": '{"factSheetId":"' + azureProviderId + '"}'
                                    # },
                                    {
                                        "op": "add",
                                        "path": "/relSubcomponentITComponentToParentalComponentITComponent/new_subcomponent" + vmComponent,
                                        "value": '{"factSheetId":"' + rgComponent + '"}' #add under rgComponent, not this resourceComponent (else all VMs are under a generic Azure Virtual Machines component)
                                    },   
                                    {
                                        "op": "replace",
                                        "path": "/osType",
                                        "value": vm['os_type']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/osFullname",
                                        "value": vm['os']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/osVersion",
                                        "value": vm['os_version']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/privateIP",
                                        "value": ", ".join(vm['privateIPAddresses'])
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/resourceGroup",
                                        "value": vm['resourceGroup']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/azureSubscriptionId",
                                        "value": vm['service_id']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/instanceType",
                                        "value": vm['vmSize']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/cpuCount",
                                        "value": vm['numberOfCores']
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/ramAllocated",
                                        "value": ramAllocated
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/diskOSSize",
                                        "value": diskOSSize
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/diskResourceSize",
                                        "value": diskSizeGB
                                    },
                                    {
                                        "op": "replace",
                                        "path": "/resourceLocation",
                                        "value": vm['location']
                                    },
                                ]

                                leanix_api.modify_factsheet(vmComponent, patches)
                

                #update the total cost for this resource group
                for rgComponent, value in totalRGCost.items():                        
                    leanix_api.update_costs(
                        parent = azureHostingComponent,\
                        factsheet_type = "ITComponent", \
                        relationship_name = "relParentalComponentITComponentToSubcomponentITComponent", \
                        factsheet_id = rgComponent,
                        costTotalAnnual = value
                    )

                print("Total costs for " + apm_id + " is calculated at: " + str(sum(totalRGCost.values())))

                #update the total cost for the Azure Hosting component
                leanix_api.update_costs(
                    parent = app_id,\
                    factsheet_type = "Application", \
                    relationship_name = "relApplicationToITComponent", \
                    factsheet_id = azureHostingComponent,
                    costTotalAnnual = sum(totalRGCost.values())                    
                )
            


# deletes all with Azure tag
leanix_api.delete_factsheets_with_tag("ITComponent", AZURE_TAG)

# generates new ones
azureToLeanIX(leanix_api, "<apm id>")


