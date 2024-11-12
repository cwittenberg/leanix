#!/usr/bin/env python

import os
import requests
import zipfile
import tempfile
import os
import sys
from queue import deque

def load_cairo():
    """Download and load cairo.dll for Windows, adding it to the PATH."""
    # URL of the ZIP file containing cairo.dll
    zip_url = "https://github.com/preshing/cairo-windows/releases/download/with-tee/cairo-windows-1.17.2.zip"

    # Temporary directory to download and extract the ZIP file
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, "cairo-windows.zip")

    # Step 1: Download the ZIP file
    response = requests.get(zip_url)
    with open(zip_path, "wb") as file:
        file.write(response.content)

    # Step 2: Extract the ZIP file
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    # Step 3: Path to the extracted cairo.dll file
    cairo_dll_path = os.path.join(temp_dir, "cairo-windows-1.17.2", "lib", "x64")

    # Step 4: Add the directory with cairo.dll to PATH
    os.environ["PATH"] += os.pathsep + cairo_dll_path

    # Clean up: Optionally delete the ZIP file
    os.remove(zip_path)


# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')
    
    # Load cairo.dll
    load_cairo()


import cairosvg

leanix_token = '<token>'
leanix_base_url = 'https://<tenant>.leanix.net/' 
leanix_auth_url = leanix_base_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_base_url + '<tenant-name>/factsheet/'
leanix_metrics_url = leanix_base_url
leanix_request_url = leanix_base_url + 'services/pathfinder/v1/graphql'


from leanix.leanix import LeanIXAPI

leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url, leanix_metrics_url, search_base_url=leanix_base_url)


### Celonis BPM

# Import the coupa API class
from celonis.celonis import CelonisBPM

CELONIS_TENANT = "<tenant name>"
CELONIS_AUTHTOKEN = "<celonis token>"

BPM = CelonisBPM(leanix_api, CELONIS_TENANT, CELONIS_AUTHTOKEN, max_depth=4, userLookupObj=None)


processes = leanix_api.get_all("BusinessContext", "process", returnAsRaw=True)

import pprint

for process in processes['data']['allFactSheets']['edges']:    
    node = process['node']
    fs_id = node['id']
    process_name = node['name']

    # check if SVG already exists on factsheet
    resources = leanix_api.get_resources_for_factsheet(fs_id)

    # if so, delete all existing resources
    for document in resources:
        leanix_api.delete_resource(document['id'])
    
    bpmnNavigatorUrl = node['externalId']['externalUrl']
    
    if bpmnNavigatorUrl is None or bpmnNavigatorUrl == '':
        continue

    bpmnID = bpmnNavigatorUrl.split('/')[-1]

    process = CelonisBPM.BPMNProcess(BPM, {'bpmnDiagramID': bpmnID})

    try:                        
        svg_image = process.getImage()

        filename = bpmnID + ".svg"
        with open(filename, "w") as f:
            f.write(svg_image)

        # Upload SVG to LeanIX
        leanix_api.upload_resource_to_factsheet(fs_id, filename, f"{process_name}.svg", "Image", process_name)

        bpmnDesignerUrl = f"https://{BPM.tenant}.symbioweb.com/{BPM.tenant}/{BPM.storagecollection}/1033/BasePlugin/GoTo/Processes/treeanddiagram/" + bpmnID

        # Add website link to the process
        leanix_api.add_website_resource_to_factsheet(fs_id, bpmnNavigatorUrl, "Open in Process Navigator", "Open in Celonis Process Navigator")                    
        leanix_api.add_website_resource_to_factsheet(fs_id, bpmnDesignerUrl, "Open in Process Designer", "Open in Celonis Process Designer")                    
        
        # Try with logo
        try:
            #print filesize of filename
            pngFilename = filename.replace(".svg",".png")

            print("source", filename)

            cairosvg.svg2png(url=filename, write_to=pngFilename)

            if os.path.getsize(filename) > 600:
                leanix_api.upload_resource_to_factsheet(fs_id, pngFilename, f"{process_name}.png", "logo", process_name + " PNG")
            else:
                print("****************************************************")
                print(f"PNG file {pngFilename} is too small. Not uploading.")
                print(fs_id, process_name)

            os.unlink(pngFilename)
        except:
            #print error
            print("****************************************************")
            print(f"Error converting {filename} to PNG")
            print(fs_id, process_name)


            pass


        os.unlink(filename)


    except Exception as e:
        print("Potential error with Symbio/Celonis (HTTP)")
        print("****************************************************")
        print(e)
        print(f"Error downloading SVG for {process_name}")
        print(fs_id, process_name)
        pass
