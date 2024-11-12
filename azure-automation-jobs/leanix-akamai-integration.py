#!/usr/bin/env python

import os
import sys
import re
import json
import pprint
from queue import deque

import os

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

# Import my LeanIX API class
from leanix.leanix import LeanIXAPI

from akamaiapi.akamaiapi import AkamaiAPI
from tldextract import extract


METRIC_DAYS = 2

leanix_token = '<token>'
leanix_base_url = 'https://<tenant>.leanix.net/' 
leanix_auth_url = leanix_base_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_base_url + '<tenant-name>/factsheet/'
leanix_metrics_url = leanix_base_url
leanix_request_url = leanix_base_url + 'services/pathfinder/v1/graphql'

leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url, leanix_metrics_url, search_base_url=leanix_base_url)

#create this schema first using leanix_api.create_schema in your tenant, below is just an example.
TRAFFIC_SCHEMA="f8de5cdd-0d2f-47a0-a7a6-740454d19720"

#create a tag, reference its ID below such that you can easily identify AKAMAI loaded factsheets. Below is just an example

TAG_AKAMAI = "f5363b2c-d017-4e3e-84e3-e13e51de5fbf"

#reference to an IT Component reflecting Akamai's CDN thats added by default
AKAMAI_COMPONENT = "4aac6e4a-bba7-440f-8d04-d3ffeb8eba32" #akamai CDN IT Component

akamai_client_secret = "<token>"
akamai_base_url = "<luna api base url>"
akamai_access_token = "<akamai access token>"
akamai_client_token = "<akamai client token>"


akamai_api = AkamaiAPI(akamai_client_token, akamai_client_secret, akamai_access_token, akamai_base_url)


##############################
# Load all existing websites #
##############################
# Representation is the Factsheet name I use, with Subtype (category): website.
existing_websites = leanix_api.get_all("Representation", "website")

existing_website_map = {}
for site in existing_websites:
    existing_website_map[site["id"]] = site["name"].upper()

##################################
# Screenshot functions           #
##################################
# If you want to attach a screenshot of each website as a Resource.
# In Azure Automation I have disabled this, so commented out here.

# import subprocess
# import sys
# from playwright.sync_api import sync_playwright

# def install_playwright_browsers():
#     """Install required browsers using Playwright via CLI."""
#     try:
#         # Install Chromium browser
#         subprocess.run(["playwright", "install", "chromium"], check=True)
#         print("Chromium browser has been installed.")
#     except subprocess.CalledProcessError as e:
#         print("Failed to install browsers via Playwright:", e)
#         sys.exit(1)

# def take_screenshot(url, output_path):
#     try:
#         with sync_playwright() as p:
#             # Launch headless browser
#             browser = p.chromium.launch(headless=True)
#             page = browser.new_page()
            
#             # Set viewport size (optional)
#             page.set_viewport_size({'width': 1024, 'height': 768})
            
#             # Navigate to the page
#             page.goto(url, wait_until='networkidle')
            
#             # # Take screenshot
#             # page.screenshot(path=output_path, full_page=True)
#             # print(f"Screenshot saved to {output_path}")

#             page.screenshot(
#                 path=output_path,
#                 full_page=False,
#                 type='jpeg',    # Use JPEG format
#                 quality=50      # Set quality between 0-100
#             )
            
#             # Close browser
#             browser.close()
#     except Exception as e:
#         print(f"An error occurred: {e}")

# install_playwright_browsers()


def is_existing_website(name):
    return name.upper() in existing_website_map.values()

def create_website(cpcode, hostname, parent_fs=None, isGrouping=False, summary=None):
    global AKAMAI_COMPONENT

    site_fs_id = None

    if not is_existing_website(hostname):
        print(f"Creating new website: {hostname}")

        url = hostname

        screenshot_file = None

        if not hostname.startswith("https://"):
            url = f"https://{hostname}"

            if not isGrouping:
                screenshot_file = f"/tmp/" + hostname.replace(" ", "-") + ".jpg"
              
                # take_screenshot(url, screenshot_file)

        # Conditionally add the externalId
        externalObj = {
            "externalId": "CP Code: " + str(cpcode)
        }

        #"{\"externalId\":\"" + str(externalId) + "\", \"externalUrl\":\"" + str(externalUrl) + "\", \"status\":\"\"}"
        externalStr = json.dumps(externalObj)            

        site_fs_id = leanix_api.create_factsheet("Representation", hostname, "website")
        leanix_api.add_tag_to_factsheet(site_fs_id, TAG_AKAMAI)

        patches= [
            {
                "op": "replace",
                "path": "/externalId",
                "value": externalStr
            }            
        ]        

        if not isGrouping:
            patches.extend([{
                "op": "replace",
                "path": "/URL",
                "value": url
            },            
            {
                "op": "replace",
                "path": "/alias",
                "value": extract_main_domain(hostname)
            }])


            if len(summary) > 0:
                summary = summary[0]

                #Show visit summary and bandwidth on the main factsheet page

                patches.extend([{
                    "op": "replace",
                    "path": "/visitspast90days",
                    "value": int(summary["edgeHitsSum"])
                },
                {
                    "op": "replace",
                    "path": "/bandwidth90days",
                    "value": int(summary["edgeBytesSum"])
                }])


        leanix_api.modify_factsheet(site_fs_id, patches=patches)

        if parent_fs is not None:
            leanix_api.create_relation_if_not_exists(site_fs_id, parent_fs, "Representation", "relToParent")
        
        leanix_api.create_relation_if_not_exists(site_fs_id, AKAMAI_COMPONENT, "Representation", "relToRequires")

    else:
        site_fs_id = [k for k, v in existing_website_map.items() if v == hostname.upper()][0]

        if site_fs_id is not None:
            if not isGrouping:
                patches = []

                if len(summary) > 0:
                    summary = summary[0]

                    patches.extend([{
                        "op": "replace",
                        "path": "/visitspast90days",
                        "value": int(summary["edgeHitsSum"])
                    },
                    {
                        "op": "replace",
                        "path": "/bandwidth90days",
                        "value": int(summary["edgeBytesSum"])
                    }])


                leanix_api.modify_factsheet(site_fs_id, patches=patches)



    return site_fs_id

def extract_main_domain(domain):
    # just leave the domain
    return extract(domain).domain

##############################
# Load from Akamai API       #
############################## 

# leanix_api.delete_factsheets_with_tag("Representation", TAG_AKAMAI)

print("Getting traffic data from Akamai API...")

traffic = akamai_api.get_traffic(sinceDaysAgo=METRIC_DAYS)

akamai_sites = {}

for entry in traffic["data"]:
    cpcode = entry["cpcode"]
    hostname = entry["hostname"]
    
    if cpcode not in akamai_sites:
        akamai_sites[cpcode] = []   

    if hostname != "Others" and hostname != "N/A":
        if hostname not in akamai_sites[cpcode]:
            akamai_sites[cpcode].append(hostname)

cntSites = 0

for cpcode, sites in akamai_sites.items():
    if len(sites) == 0:
        continue

    if cpcode == "" or cpcode is None:
        print("ERROR - cpcode is empty")
        exit(1)

    parent_fs = create_website(cpcode, f"Akamai {cpcode}", isGrouping=True)

    if parent_fs is None:
        print("ERROR - could not create parent website")
        exit(1)

    print("Parent: ", parent_fs)

    for site in sites:
        summary = akamai_api.get_metrics_by_hostname(hostname=site, includeTimeDimension=False, sinceDaysAgo=90)

        fs_id = create_website(cpcode, site, parent_fs, summary=summary)

        timeseries = akamai_api.get_metrics_by_hostname(factsheetId=fs_id, hostname=site, sinceDaysAgo=METRIC_DAYS)

        leanix_api.metric_add_website_traffic(fs_id, TRAFFIC_SCHEMA, timeseries)


        cntSites += 1

        if cntSites % 50 == 0:
            leanix_api._authenticate() #reauthenticate to avoid timeout

            print("LeanIX: Reauthenticated")
            print(f"Processed {cntSites} sites out of {len(akamai_sites)}")

