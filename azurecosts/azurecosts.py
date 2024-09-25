import json
import requests
import warnings
from urllib3.exceptions import InsecureRequestWarning
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Disable InsecureRequestWarnings if needed
warnings.simplefilter('ignore', InsecureRequestWarning)

from datetime import datetime, timedelta

class Azurecosts:
    auth_url = "https://login.microsoftonline.com/<tenantid>/oauth2/v2.0/token"
    cost_management_url = "https://management.azure.com/providers/Microsoft.Management/managementGroups/anmgsecurity/providers/Microsoft.CostManagement/query?api-version=2021-10-01&$top=5000"

    def __init__(self, client_id, client_secret):
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
    def _call(self, url, json_payload):
        try:
            # Send the POST request to the provided URL with the payload
            response = requests.post(url, headers=self.header, json=json_payload, verify=False, timeout=10)
            response.raise_for_status()  # Raise an error for bad status codes (4xx, 5xx)
            
        except requests.exceptions.RequestException as e:
            if response and response.status_code == 401:
                print("Unauthorized. Re-authenticating...")
                self.token = self._authenticate(self.client_id, self.client_secret)
                self.header['Authorization'] = f'Bearer {self.token}'
                return self._call(url, json_payload)  # Retry the call after re-authentication
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
