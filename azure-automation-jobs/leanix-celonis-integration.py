#!/usr/bin/env python

"""
This Azure Automation job creates an inmemory representation of the process graph, persists it and walks the tree to generate an identical Business Context structure in LeanIX.
This runbook should be ran preceding leanix-celonis-bpmn-integration (for also uploading the BPMN graphs)
"""

import os
import sys
import re
import json
import pprint
from queue import deque

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

MAX_DEPTH=4

### Search for user (graph API) in AzureAD - for populating GPOs
azure_tenant_id = ""
azure_client_id = ""
azure_client_secret = ""

from typing import Type

from users.UserGraph_base import UserGraph
from users.AzureADUserFetcher import AzureADUserFetcher

# Initialize the Azure AD user graph
usergraph: Type[UserGraph] = AzureADUserFetcher(azure_tenant_id, azure_client_id, azure_client_secret)

### LeanIX

azureProviderId = "46778ee2-444f-4caf-8f27-e7743a6f53d8"

leanix_token = '<token>'
leanix_base_url = 'https://<tenant>.leanix.net/' 
leanix_auth_url = leanix_base_url + 'services/mtm/v1/oauth2/token'
leanix_factsheet_base_url = leanix_base_url + '<tenant-name>/factsheet/'
leanix_metrics_url = leanix_base_url
leanix_request_url = leanix_base_url + 'services/pathfinder/v1/graphql'

TAG_CELONIS = "60392c59-2e93-464d-b87e-2b998a17de70"  #this is a tag we add to every created BusinessContext/Process. Create a tag in your tenant first and use the same ID here.  

from leanix.leanix import LeanIXAPI

leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url, leanix_metrics_url, search_base_url=leanix_base_url)


### Celonis BPM

# Import the coupa API class
from celonis.celonis import CelonisBPM

CELONIS_TENANT = "<celonis tenant>"
CELONIS_AUTHTOKEN = "<celonis token>"

BPM = CelonisBPM(leanix_api, CELONIS_TENANT, CELONIS_AUTHTOKEN, max_depth=MAX_DEPTH, userLookupObj=usergraph)

ROOT_PROCESS_ID = "59ed90c5-6a55-45d4-91b9-c78b0ae8a4e9"

ROOT_PROCESS_ID_LEANIX = None
DOWNLOAD_SVG = False


import pickle


def load_all_processes(bpm_instance, root_process_id):
    root_process = bpm_instance.get_process(root_process_id)
    process_tree = build_process_tree(bpm_instance, root_process)
    return process_tree

def build_process_tree(bpm_instance, process, visited=None, current_depth=0):
    if visited is None:
        visited = {}

    # Check for maximum depth
    if current_depth >= bpm_instance.max_depth:
        return visited

    # Skip if already visited
    if process.getID() in visited:
        return visited
    
    # Skip if process is not in effect
    if "state1" not in process.attributes:
        return visited

    # Check if process should be skipped
    state1 = process.attributes.get("state1", "inEffect")
    process_name = process.attributes.get("name", "").lower()
    
    if process.attributes.get("bpmnDiagramID") != ROOT_PROCESS_ID:
        theID = process.getID()
    
        if theID is None or theID == "":
            print("***********************************************************")
            print(f"Skipping process {process_name} with empty ID")
            print("***********************************************************")
            return visited

        if process_name == "temporary library" or state1 != "inEffect" or "temporary library" in process_name.lower():
            print("***********************************************************")
            print(f"Skipping process {process_name} with state {state1}")
            print("***********************************************************")
            return visited

        # Calculate dot count
        visualProcessID = process.getID()
        dot_count = visualProcessID.count(".") if visualProcessID else 0

        # Skip processes with dot count greater than 2
        if dot_count >= MAX_DEPTH  or current_depth >= MAX_DEPTH:
            return visited
        


    # Now that all checks are passed, add the process to visited
    visited[process.getID()] = process

    # Load children after all checks
    process.loadChildren()

    # Recursively process all children
    for child in process.getChildren():
        build_process_tree(bpm_instance, child, visited, current_depth + 1)

    return visited


def persist_tree_to_disk(process_tree, filename="process_tree.pkl"):
    with open(filename, 'wb') as f:
        pickle.dump(process_tree, f)
    print(f"Process tree persisted to disk at {filename}")



#load process_tree.pkl to recover the process tree if the file exists
#check if file exists
import os
if os.path.exists('process_tree.pkl'):
    with open('process_tree.pkl', 'rb') as f:
        process_tree = pickle.load(f)
else:
    print("Processing tree from scratch")
    process_tree = load_all_processes(BPM, ROOT_PROCESS_ID)
    persist_tree_to_disk(process_tree)


def persist_process_tree_to_leanix(process_tree, max_depth):
    """
    Walks through the entire process tree and persists each process in LeanIX under the correct parent.
    """

    visited_relationships = set()  # Initialize visited relationships to avoid duplicates

    def process_node(node_id, parent_fs_id=None, current_depth=0):
        """
        Recursive function to process each node and persist it under the correct parent.
        """
        if current_depth >= max_depth:
            return

        node = process_tree.get(node_id)
        if node is None:
            return  # Node not in process_tree

        # Skip if the process is named "Temporary Library"
        process_name = node.attributes.get("name", "").strip().lower()
        if "temporary library" in process_name:
            print(f"Skipping process {process_name} at depth {current_depth}")
            return
        
        bpmnID = node.attributes.get("bpmnDiagramID")

        if node.get_parent() is None and bpmnID != ROOT_PROCESS_ID:
            print(f"Skipping process {process_name} at depth {current_depth}")
            print("Cannot find parent that should be attached to this node")
            print("Node information:", node.attributes)
            return
        

        print("\nNow processing ", node.attributes.get("name", "Unknown process"), "with ID", node.attributes.get("id", "Unknown ID"))

        nodeID = node.getID()

        if nodeID is not None:
            if not "." in nodeID and len(nodeID) > 0:
                #this is a main process, so also get GPO
                node.attributes["customGponame"] = node.get_gpo(bpmnID)

                print("found GPO for ", node.attributes.get("name", "Unknown process"), "with GPO", node.attributes.get("customGponame"))



        # Create or update the current process in LeanIX
        current_fs_id = node.create_or_update_in_leanix(parent_fs_id=parent_fs_id, visited_relationships=visited_relationships)


        if current_fs_id is not None:
            # Process all children recursively
            for child in node.getChildren():
                child_id = child.getID()
                if child_id in process_tree:
                    process_node(child_id, parent_fs_id=current_fs_id, current_depth=current_depth + 1)

    # Start with each root node (those without a parent) and walk through the tree
    for process_id, current_process in process_tree.items():
        parent_process = current_process.get_parent()
        if parent_process is None:
            # Root process, no parent
            print(f"Processing root process: {current_process.attributes.get('name')}")
            process_node(process_id, current_depth=0)



# Main execution
# leanix_api.delete_factsheets_with_tag("BusinessContext", TAG_CELONIS)


# Call the function with the desired max depth
persist_process_tree_to_leanix(process_tree, max_depth=MAX_DEPTH)
