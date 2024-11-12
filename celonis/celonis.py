"""
Class to interoperate with Celonis Process Modeler (formerly known as Symbio)
Supports also loading BPMN diagrams as SVG and PNG - though depends on cairosvg. 
In code cairosvg dependency has been commented out, I decided to run this in a separate job on Azure Automation (to cope with 3 hour time limit for large repositories) 
"""
import requests
import json
import logging
import re
import os
from html import unescape
import os
import requests
# import cairosvg
import traceback

from typing import Type
from users.UserGraph_base import UserGraph

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

def clean_svg(svg_content):
    """
    Preprocess and clean the SVG file to ensure invalid attributes are handled.
    For example, we replace empty 'fill-opacity' attributes with a default value.
    """
    svg_content=svg_content.replace('fill-opacity:1;', 'fill-opacity:1.0;')
    svg_content=svg_content.replace('fill-opacity:;', '')

    return svg_content

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

DOWNLOAD_SVG = False


class CelonisBPM:
    """
    A class to interact with the Celonis Process Manager API (formerly known as Symbio).
    """
    GPO_MAP = {} # Map to store GPOs for processes (customization in our Symbio tenant)

    def __init__(self, leanix_api, tenant, authtoken, storagecollection="Processworld", processfacet="processes", lcid=1033, max_depth=3, userLookupObj: Type[UserGraph] = None):
        self.storagecollection = storagecollection
        self.tenant = tenant
        self.lcid = lcid
        self.processfacet = processfacet
        self.max_depth = max_depth

        self.headers = {
            'symbio-auth-token': authtoken
        }

        self.base_url = f'https://{tenant}.symbioweb.com/{tenant}/{storagecollection}'
        self.data_url = f'{self.base_url}/_api/v2/data/elements'
        self.bpmn_url = f'{self.base_url}/_api/v1/bpmn'

        self.userLookupObj = userLookupObj

        self.leanix_api = leanix_api

    def _sanitize(self, text) -> str:
        return re.sub('<[^<]+?>', '', text)
    

    class BPMNProcess:
        """
        Represents a BPMN process in Celonis.
        """
        parent = None
        def __init__(self, celonisClass, attributes, childIDs=[]):
            self.attributes = attributes
            self.childIDs = childIDs
            self.celonisClass = celonisClass
            self.children = []
            self.loaded = False            

        def extract_version_number(self,text):
            match = re.search(r'^\d+(\.\d+)*', text)
            return match.group(0) if match else None

        def remove_leading_version(self,text):
            pattern = r'^\d+(?:\.\d+)*\.*\s*'
            return re.sub(pattern, '', text)

        def __str__(self):
            return json.dumps(self.to_dict(), indent=4)
        
        def getID(self):
            if "id" in self.attributes:
                return self.attributes.get('id')
            else:
                return self.extract_version_number(self.attributes.get('name'))
            
        def to_dict(self, visited=None):
            if visited is None:
                visited = set()

            obj_id = id(self)
            if obj_id in visited:
                return {'Attributes': self.attributes, 'Children': 'Recursive reference detected'}

            visited.add(obj_id)

            # Ensure children are loaded before serialization
            if not self.loaded:
                self.loadChildren()

            # Recursively convert children to dictionaries
            children_list = [child.to_dict(visited) for child in self.children]

            return {
                'Attributes': self.attributes,
                'Children': children_list
            }
        
        def get_parent(self):
            """
            Method to retrieve the direct parent of the current process.
            Returns the parent process or None if no parent is found.
            """
            return self.parent
        

        def get_gpo(self, processID):
            return self.celonisClass.get_custom_attribute(processID, "customGponame")
        
        def set_attribute(self, key, value):
            self.attributes[key] = value

        def loadChildren(self):
            """
            Load the children of the current process.
            """
            for childId in self.childIDs:
                child = self.celonisClass.get_process(childId)
                child.parent = self  # Set this process as the parent of the child
                self.children.append(child)

            self.loaded = True

        def getChildren(self):
            if not self.loaded:
                self.loadChildren()
            return self.children
        
        def _sanitize(self, str) -> str:
            text_only = re.sub('<[^<]+?>', '', str)

            return text_only
        
        def getImage(self):
            """
            Returns the BPMN diagram as an SVG image.
            """
            processID = self.attributes["bpmnDiagramID"]
            bpmn_xml_string = self.celonisClass.get_bpmn(processID)    

            # Strip leading whitespace or newlines
            bpmn_xml_string = bpmn_xml_string.lstrip()

            # Use a regular expression to find the symbioSvg element
            match = re.search(r'<symbioSvg[^>]*>(.*?)</symbioSvg>', bpmn_xml_string, re.DOTALL)
            if not match:
                raise ValueError('No symbioSvg element found in BPMN XML.')

            # Get the escaped SVG content
            svg_escaped = match.group(1)
            if not svg_escaped:
                raise ValueError('symbioSvg element is empty.')

            # Unescape the SVG content
            svg_content = unescape(svg_escaped)

            return clean_svg(svg_content)            

        def create_or_update_in_leanix(self, parent_fs_id=None, visited_relationships=None, max_depth=3):
            """
            Creates or updates a process in LeanIX and assigns an alias.
            Returns the LeanIX FactSheet ID.
            """

            dot_count = 0
            alias = self.getID()
            if alias is not None and alias != "":
                dot_count = alias.count(".")

            if dot_count > max_depth:
                print("Skipping process with alias", alias, "due to depth limit.")
                return None

            # Initialize visited_relationships if not provided
            if visited_relationships is None:
                visited_relationships = set()

            process_name = self.remove_leading_version(self.attributes.get('name')).strip()

            #remove characters from process name that are not allowed in LeanIX' name
            process_name = re.sub(r'[^\x00-\x7F]+', ' ', process_name)
            process_name = re.sub(r'[^\w\s-]', '', process_name).strip()
            process_name = process_name.replace(";", ",")
            
            process_id = None

            # Check if the process already exists or needs to be created
            if parent_fs_id is None:
                # It's a root process
                results = self.leanix_api.search(process_name)
                if results:
                    for fs in results:
                        if fs['type'] == "BusinessContext" and fs['name'] == process_name:
                            process_id = fs['id']
                            break
                    else:
                        process_id = self.leanix_api.create_factsheet("BusinessContext", process_name, "process")
                else:
                    process_id = self.leanix_api.create_factsheet("BusinessContext", process_name, "process")
            else:
                # It’s a child process, link it to the parent
                if (parent_fs_id, process_name) not in visited_relationships:
                    print(f"Creating '{process_name}' as child of '{parent_fs_id}'")
                    process_id = self.leanix_api.create_if_not_exists(
                        "BusinessContext",
                        process_name,
                        "process",
                        createAsChildOf=parent_fs_id,
                        relationshipName="relToChild"
                    )
                    visited_relationships.add((parent_fs_id, process_name))
                else:                
                    print(f"Skipping creation of '{process_name}' under '{parent_fs_id}' to avoid duplicate relationship.")
                    
                    # Get the existing process ID
                    results = self.leanix_api.search(process_name)
                    if results:
                        for fs in results:
                            if fs['type'] == "BusinessContext" and process_name in fs['name']:
                                process_id = fs['id']
                                break
                    

            # Update the process with additional attributes if needed
            if process_id is not None:
                patches = []

                if 'description' in self.attributes and self.attributes['description'] is not None:
                    patches.append({
                        "op": "replace",
                        "path": "/description",
                        "value": self._sanitize(self.attributes['description'])
                    })

                
                
                if 'customGponame' in self.attributes and self.attributes['customGponame'] is not None:
                    name = self.attributes['customGponame'].replace("GPO", "").strip()

                    print(f"Looking up user for GPO {name}...")
                    
                    if self.celonisClass.userLookupObj is not None:                        
                        users = self.celonisClass.userLookupObj.search_user_by_name(name, reauthenticate=True)
                        
                        if users is not None and len(users) == 1:
                            user = users[0]

                            name = user.get('displayName')
                            email = user.get('mail')
                            surname = user.get('surname')
                            firstname = user.get('givenName')
                            jobtitle = user.get('jobTitle')

                            print(f"Found user {name} for GPO {self.attributes['customGponame']}")

                            DEFAULT_ROLE_ID="319ee7ee-96d4-4bca-a331-bc78031a30e8"

                            # check if any subscription preexists with same role id
                            subscriptions = self.leanix_api.get_subscriptions(process_id)
                            for subscription in subscriptions:
                                for role in subscription['roles']:
                                    if role['id'] == DEFAULT_ROLE_ID:
                                        self.leanix_api.delete_subscription(subscription['id'])

                            self.leanix_api.add_subscription(process_id, DEFAULT_ROLE_ID, email, firstname, surname)
                            
                            self.celonisClass.GPO_MAP[self.getID()] = {
                                "role": DEFAULT_ROLE_ID,
                                "email": email,
                                "firstname": firstname,
                                "surname": surname,
                            }
                else:
                    ### Inherit GPO from Main Process for all processes underneath

                    theID = self.getID()
                    if theID is not None:
                        if "." in theID:
                            mainProcess = theID.split(".")[0]
                            if mainProcess in self.celonisClass.GPO_MAP:
                                gpo = self.celonisClass.GPO_MAP[mainProcess]

                                # check if any subscription preexists with same role id
                                subscriptions = self.leanix_api.get_subscriptions(process_id)
                                for subscription in subscriptions:
                                    for role in subscription['roles']:
                                        if role['id'] == gpo["role"]:
                                            self.leanix_api.delete_subscription(subscription['id'])                                    

                                self.leanix_api.add_subscription(process_id, gpo["role"], gpo["email"], gpo["firstname"], gpo["surname"])
                

                targetUrl = f"https://navigator.symbio.cloud/{self.celonisClass.tenant}/e9f3b0a5-bd6b-4d24-864b-5c14f4b30b59/journal/{self.attributes['bpmnDiagramID']}"


                externalObj = {
                    "externalId": "Open in Celonis Process Navigator",
                    "externalUrl": targetUrl,
                    "comment": "test",
                    "status": "active"
                }
                externalStr = json.dumps(externalObj)

                if 'createdOn' in self.attributes and 'validFrom' in self.attributes and 'validUntil' in self.attributes:
                    lifecycle = {
                        "phases": [
                            {"phase": "active", "startDate": self.attributes['validFrom'].split('T')[0]},
                        ]
                    }
                    if not self.attributes['validUntil'].startswith('9999'):
                        lifecycle["phases"].append({"phase": "endOfLife", "startDate": self.attributes['validUntil'].split('T')[0]})
                    lifecycleStr = json.dumps(lifecycle)

                    patches.append({
                        "op": "replace",
                        "path": "/lifecycle",
                        "value": lifecycleStr
                    })

                if 'majorVersion' in self.attributes and 'minorVersion' in self.attributes:
                    patches.append({
                        "op": "replace",
                        "path": "/Version",
                        "value": f"{self.attributes['majorVersion']}.{self.attributes['minorVersion']}"
                    })

                # newAlias = self.attributes.get('id')#self.extract_version_number(self.attributes.get('name'))

                patches.extend([
                    {
                        "op": "replace",
                        "path": "/tags",
                        "value": f'[{{"tagId":"{TAG_CELONIS}"}}]'
                    },
                    {
                        "op": "replace",
                        "path": "/alias",
                        "value": self.attributes.get('id')
                    },
                    {
                        "op": "replace",
                        "path": "/externalId",
                        "value": externalStr
                    }
                ])

                try:
                    self.leanix_api.modify_factsheet(process_id, patches)
                except:
                    print("****************************************************")
                    print(f"Archiving newly created sheet. Error modifying factsheet {process_id} with patches {patches}")
                    print(process_id, process_name)
                    
                    self.leanix_api.archive_factsheet(process_id)
                    pass

                # Write SVG to disk if DOWNLOAD_SVG is enabled
                # Note that this is not enabled by default - I recommend to call this from a secondary job when scheduled in Azure Automation
                if DOWNLOAD_SVG:
                    # check if SVG already exists on factsheet
                    resources = self.leanix_api.get_resources_for_factsheet(process_id)

                    # if so, delete all existing resources
                    for document in resources:
                        self.leanix_api.delete_resource(document['id'])

                    try:                        
                        self.attributes['svg'] = self.getImage()

                        filename = self.attributes['bpmnDiagramID'] + ".svg"
                        with open(filename, "w") as f:
                            f.write(self.attributes['svg'])

                        # Upload SVG to LeanIX
                        self.leanix_api.upload_resource_to_factsheet(process_id, filename, f"{process_name}.svg", "Image", process_name)

                        targetUrl = self.attributes.get('gotoUrl')

                        #This switch unfortunately is not working.
                        #Use Navigator instead of Designer
                        #ie. https://<tenant>.symbioweb.com/<company>/Processworld/1033/BasePlugin/GoTo/Processes/treeanddiagram/ff614b54-9349-4736-8370-7bbe4377aa65
                        #--> https://navigator.symbio.cloud/<company>/<data pool id>

                        # targetUrl = targetUrl.replace(f"https://{self.celonisClass.tenant}.symbioweb.com/{self.celonisClass.tenant}/{self.celonisClass.storagecollection}/1033/BasePlugin/GoTo/Processes/treeanddiagram/",
                        targetUrl = f"https://navigator.symbio.cloud/{self.celonisClass.tenant}/<fill your symbio data/collection ID here>/journal/{self.attributes['bpmnDiagramID']}"

                        # Add website link to the process
                        self.leanix_api.add_website_resource_to_factsheet(process_id, targetUrl, "Open in Process Navigator", "Open in Celonis Process Navigator")                    
                        self.leanix_api.add_website_resource_to_factsheet(process_id, self.attributes.get('gotoUrl'), "Open in Process Designer", "Open in Celonis Process Designer")                    

                        try:
                            pngFilename = filename.replace(".svg",".png")

                            print("source", filename)

                            #commented out so you dont have the cairosvg dependency by default
                            # cairosvg.svg2png(url=filename, write_to=pngFilename)

                            if os.path.getsize(filename) > 600:
                                self.leanix_api.upload_resource_to_factsheet(process_id, pngFilename, f"{process_name}.png", "logo", process_name + " PNG")
                            else:
                                print("****************************************************")
                                print(f"PNG file {pngFilename} is too small. Not uploading.")
                                print(process_id, process_name)

                            os.unlink(filename.replace(".svg",".png"))
                        except:
                            #print error
                            print("****************************************************")
                            print(f"Error converting {filename} to PNG")
                            print(process_id, process_name)

                            #see error details
                            traceback.print_exc()

                            pass


                        os.unlink(filename)
                    except Exception as e:
                        print("Potential error with Symbio/Celonis (HTTP)")
                        print("****************************************************")
                        print(e)
                        print(f"Error downloading SVG for {process_name}")
                        print(process_id, process_name)
                        pass

            else:
                print("WARNING!")
                print("****************************************************")
                print(f"Skipping process '{process_name}' due to missing process ID.")
                print("Parent FS ID:", parent_fs_id)
                print("Attributes:", self.attributes)

            return process_id


    def get_bpmn(self, processID):
        return self._call(processID, apiUrl=self.bpmn_url, arguments={"exportRepositoryElements": True}, isJSON=False)


    def get_process(self, processID=None):
        raw = self._call(processID)
        kv = {}

        if "attributes" in raw:
            for attribute in raw['attributes']:
                if attribute["key"] == "tileImage":
                    continue

                values = [v['value'] for v in attribute["values"] if "value" in v]
                if len(values) == 1:
                    kv[attribute["key"]] = values[0]
                    if attribute["key"] == "gotoUrl":
                        kv["bpmnDiagramID"] = values[0].split("/")[-1]
                elif len(values) > 1:
                    kv[attribute["key"]] = values
                else:
                    kv[attribute["key"]] = None

        children = [
            child["id"] for child in raw.get("children", [])
            if "properties" in child and child["properties"].get("facetName") == self.processfacet
        ]        

        return self.BPMNProcess(self, kv, list(set(children)))
    
    def get_custom_attribute(self, processID, attributeName):
        details = self._call(processID, arguments={"View": "detail"})

        if "attributes" in details:
            for attribute in details["attributes"]:
                if attribute["key"] == attributeName:
                    values = [v['value'] for v in attribute["values"] if "value" in v]
                    if len(values) == 1:
                        return values[0]
                    elif len(values) > 1:
                        return values
                    else:
                        return None                    
        
        return None
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=before_sleep_log(logger, logging.INFO)
    )
    def _call(self, query=None, arguments={}, apiUrl=None, isJSON=True):
        call_url = apiUrl if apiUrl else self.data_url
        if query is not None:
            call_url += f"/{query}"

        parts = [f"Facet={self.processfacet}", f"Lcid={self.lcid}"]
        for k, v in arguments.items():
            parts.append(f"{k}={v}")

        if arguments:
            call_url += ("&" if "?" in call_url else "?") + "&".join(parts)

        response = requests.get(url=call_url, headers=self.headers, verify=False, timeout=20)
        response.raise_for_status()
        return response.json() if isJSON else response.text

