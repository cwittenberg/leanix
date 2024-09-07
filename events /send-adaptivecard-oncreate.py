import requests
import json
from requests.auth import HTTPBasicAuth
import warnings
from urllib3.exceptions import InsecureRequestWarning

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)



webhook_url = "<your Teams webhook url>"

leanix_token = '<token>'
leanix_request_url = 'https://<tenant>.leanix.net/' 
leanix_auth_url = leanix_request_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_request_url + '<tenant-name>/factsheet/'


# Suppress only the InsecureRequestWarning from urllib3
warnings.simplefilter('ignore', InsecureRequestWarning)


def authenticate(auth_url, api_token):
    # Get the bearer token
    response = requests.post(auth_url, auth=('apitoken', api_token),
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

def call(request_url, data={}, dump=True, header={}, method='POST'):        
        if dump:
            json_data = json.dumps(data)
        else:
            json_data = data


        try:
            # print(json_data)  # For debugging purposes
            if method == 'POST':
                response = requests.post(request_url, headers=header, data=json_data, verify=False, timeout=10)
            elif method == 'GET':
                response = requests.get(request_url, headers=header, verify=False, timeout=10)
            # print(response.text)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if response:
                #check if error is a 401
                if response.status_code == 401:
                    print("Unauthorized. Re-authenticating...")
                    header = authenticate(leanix_auth_url, leanix_token)
                    return call(request_url, data, dump, header)
                else:
                    # print(response.text)
                    pass
            
            print(f"Request failed: {e}")
            raise
        
        return response


import base64

def get_user_details(token, user_id):
    user_details_url = f"https://<tenant>.leanix.net/services/mtm/v1/workspaces/<your-workspace-id>/users/{user_id}"
    picture_url = f"https://<tenant>.leanix.net/services/storage/v1/users/{user_id}/avatar?size=medium"


    response = call(user_details_url, header=token, method='GET')
    user_data = response.json().get("data", {})
    print(user_data)
    mail = user_data.get("email", "Unknown Mail")
    username = user_data.get("displayName", "Unknown User")

    picture_response = call(picture_url, header=token, method='GET', dump=False)
    picture_binary = picture_response.content
    picture_base64 = base64.b64encode(picture_binary).decode('utf-8')

    return username, mail, picture_base64



def send_teams_message(title, text, mail, picture_base64, appendBlocks=[], mailTitle="", factsheetUrl=""):
    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.3",
                    "body": [
                        {
                            "type": "ColumnSet",
                            "columns": [
                                {
                                    "type": "Column",
                                    "width": "auto",
                                    "items": [
                                        {
                                            "type": "Image",
                                            "url": f"data:image/png;base64,{picture_base64}",
                                            "size": "Medium",
                                            "style": "Person"  # This can be used for circular user profile pictures
                                        }
                                    ]
                                },
                                {
                                    "type": "Column",
                                    "width": "stretch",
                                    "items": [
                                        {
                                            "type": "TextBlock",
                                            "text": title,
                                            "size": "Large",
                                            "weight": "Bolder"
                                        },
                                        {
                                            "type": "TextBlock",
                                            "text": text,
                                            "wrap": True
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Open Factsheet",
                            "url": factsheetUrl
                        },
                        {
                            "type": "Action.OpenUrl",
                            "title": "Open Teams Chat",
                            "url": "https://teams.microsoft.com/l/chat/0/0?users=" + mail
                        },
                        {
                            "type": "Action.OpenUrl",
                            "title": "Send mail",
                            "url": "mailto:" + mail + "?subject=Regarding " + mailTitle
                        }
                    ]
                }
            }
        ]
    }

    
    if len(appendBlocks) > 0:
        data['attachments'][0]['content']['body'].extend(appendBlocks)

    response = requests.post(webhook_url, headers=headers, data=json.dumps(data))

    # Check the response
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")








def runbook_main(webhookData):
    if webhookData:
        factsheetName = webhookData['factsheetName']
        factsheetType = webhookData['factsheetType']
        user_id = webhookData['userId']

        if factsheetType == "ITComponent":
            factsheetType = "IT Component"
        
        token = authenticate(leanix_auth_url, leanix_token)
        username, mail, picture = get_user_details(token, user_id)

        factsheetId = webhookData['factsheetId']
        factsheetUrl = leanix_factsheet_base_url + factsheetType + f"/{factsheetId}"

        teams_msg_title = f"{factsheetName} created"
        teams_msg_text = f"{username} created {factsheetType}: **{factsheetName}** in LeanIX"

        send_teams_message(teams_msg_title, teams_msg_text, mail, picture, [], factsheetName, factsheetUrl)



import sys

def prepare_input():
    """
    This function processes the input from a list of arguments, extracts relevant parts from the input string,
    parses it as JSON, and then calls runbook_main with the parsed data.
    
    Returns:
    - dictionary
    """

    args_list = sys.argv

    if len(args_list) > 1:
        args = "".join(args_list)  # Concatenates all parts of the arguments into a single string
        
        print("Raw input:")
        input_str = args.split("RequestBody:")[1]
        
        print("\nStep 1")
        print(input_str)

        print("\nStep 2")
        input_str = input_str.split(",RequestHeader")[0]

        print("\nParsed input:")
        print(input_str)
        webhookData = json.loads(input_str)

        print("\nDict:")
        print(webhookData)

        return webhookData


webhookData = prepare_input()
runbook_main(webhookData)
