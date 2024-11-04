import os
import sys
import re
import json
import pprint
from datetime import datetime

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

# Import my LeanIX API class
from leanix.leanix import LeanIXAPI


leanix_token = '<your token>'
leanix_base_url = 'https://<your tenant>.leanix.net/' 
leanix_auth_url = leanix_base_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_base_url + '<your tenant name>Live/factsheet/'
leanix_metrics_url = leanix_base_url
leanix_request_url = leanix_base_url + 'services/pathfinder/v1/graphql'

leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url, leanix_metrics_url, search_base_url=leanix_base_url)

#####################################
#   Prepare for metrics gathering   #
#####################################

METRIC_SCHEMA_USERS = {
    "name": "NumberOfUsers",
    "guid": "62a3fe63-55ae-496e-8197-503ae5dfc187"   #you can create these schemas using the leanixapi.create_metric_schema method (see class)
}
METRIC_SCHEMA_DOWNLOAD = {
    "name": "dataDownload",
    "guid": "6527040a-e06a-4e09-92c7-9e3f1f54f6a2"   #you can create these schemas using the leanixapi.create_metric_schema method (see class)
}
METRIC_SCHEMA_UPLOAD = {
    "name": "dataUpload",
    "guid": "605c0a8b-342f-473b-803a-14ed679eb1a4"   #you can create these schemas using the leanixapi.create_metric_schema method (see class)
}

def register_metric(factsheet_id, metric_schema, value):
    global leanix_api
    
    today = datetime.now().strftime('%Y-%m-%d')

    register_measurement = {
        "date": today,
        "value": value,
        "seriesType": "User Traffic",
        "resourceGroup": "Zscaler"
    }

    leanix_api.metric_add_timeseries_data(factsheet_id, schema_uuid=metric_schema, timeseries_data=[register_measurement])

#####################################
# Get utilization data from Zscaler #
#####################################

ZSCALER_DISCOVERY = "fca406e4-b889-4a6b-8262-d67a6f41f28b" #this is the guid identifying your Zscaler integration

linked = leanix_api.get_discovery_linked_apps(ZSCALER_DISCOVERY)

utilization = leanix_api.get_discovery_utilization("Zscaler", linked)



for factsheetId in utilization:
    patches = []
    
    if 'usersCount' in utilization[factsheetId]:
        metric_value = utilization[factsheetId]['usersCount']
        patches.append({
            "op": "replace",
            "path": "/numberOfUsers",
            "value": metric_value
        })

        register_metric(factsheetId, METRIC_SCHEMA_USERS['guid'], metric_value)

    if 'bytesDownloaded' in utilization[factsheetId]:
        metric_value = int(utilization[factsheetId]['bytesDownloaded']/1024/1024)
        patches.append({
            "op": "replace",
            "path": "/dataDownloaded",
            "value": metric_value
        })

        register_metric(factsheetId, METRIC_SCHEMA_DOWNLOAD['guid'], metric_value)

    if 'bytesUploaded' in utilization[factsheetId]:
        metric_value = int(utilization[factsheetId]['bytesUploaded']/1024/1024)
        patches.append({
            "op": "replace",
            "path": "/dataUploaded",
            "value": metric_value
        })        

        register_metric(factsheetId, METRIC_SCHEMA_UPLOAD['guid'], metric_value)
    
    if len(patches) > 0:
        # Update the factsheet to reflect the new data

        try:
            leanix_api.modify_factsheet(factsheetId, patches)
        except Exception as e:
            print(f"Error updating {utilization[factsheetId]['name']}: {e}")
            if "Updating an archived" in str(e):
                print("Ignoring as this was an archived factsheet")
                pass

    
        print(f"Done for {utilization[factsheetId]['name']}")
    else:
        print(f"No data for {utilization[factsheetId]['name']}")


