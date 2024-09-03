import os
import sys
import re

# detect if on Windows
if os.name == 'nt':
    # Windows only:
    # Ensures the current directory is in the path
    sys.path.append('.')

# Import my LeanIX API class
from leanix.leanix import LeanIXAPI

# Import the coupa API class
from coupa.coupa import CoupaAPI

appCache = None
supplierCache = []

def detectApp(description, supplier=None):
    global appCache
    global supplierCache

    if appCache is None:
        appCache = leanix_api.get_all("Application")
        supplierCache = leanix_api.get_all("Provider")

    description = description.lower()
    supplier = supplier.lower()

    #detect if any of the apps - or its aliases (if present) - are in the description
    #detect also if any of the combinations of supplier and app are in the description

    appId = None
    domains = None
    cnt = 0

    for app in appCache:
        searchStr = " " + app['name'].lower().replace(supplier + " ", "")

        if searchStr in description:
            appId = app['id']
            cnt += 1

        #search for aliases
        if cnt == 0:
            if 'alias' in app:
                if app['alias'] is not None:
                    if " " + app['alias'].lower() + " " in description:
                        appId = app['id']
                        cnt += 1

        #search for supplier and app combination
        if cnt == 0:
            searchStr = " " + supplier + " " + app['name'].lower()
            if searchStr in description:
                appId = app['id']
                cnt += 1

            #search for aliases
            if cnt == 0:
                if 'alias' in app:
                    if app['alias'] is not None:
                        searchStr = " " + supplier + " " + app['alias'].lower()
                        if searchStr in description:
                            appId = app['id']
                            cnt += 1

    if cnt == 1:
        print("APP FOUND: " + str(appId))   
        # app is known, so source all the domain relationship from this app, if existing
        domains = leanix_api.get_relationships(appId, "Application", "relApplicationToDomain")

        return appId, domains
    else:
        appId = None


    return appId, domains




def sanitize_title(title):
    # Define the regex pattern to match dates like DD-MM-YYYY or DD/MM/YYYY
    date_pattern = r'\b\d{2}[-/]\d{2}[-/]\d{4}\b'
    
    # Define the regex pattern to match text within parentheses
    parentheses_pattern = r'\s*\([^)]*\)'    
    
    # First, remove dates
    title = re.sub(date_pattern, '', title)
    
    # Then, remove text within parentheses
    title = re.sub(parentheses_pattern, '', title)
    
    title = title.replace("EMEA_", "").replace("APAC_", "").replace("GLO_", "").replace("FO_", "").replace("_", " ")
    title = title.replace("OrderForm", "").replace("Order Form", "").replace("orderform", "").replace("order form", "")

    # Remove any leading or trailing whitespace that might result
    sanitized_title = title.strip()
    
    return sanitized_title



leanix_api = None

import datetime

def parseContract(contract):
    global leanix_api
 
    print(contract)

    #skip contracts where no value is known and no lifecycle dates are present
    if (contract['min-commitment'] == 0 or contract['start-date'] is None) or \
        (" fa:" in contract['name'].lower()) or \
        (contract['min-commitment'] == 0 and (" fa " in contract['name'].lower() or "feedback agreement" in contract['name'].lower() or "sap fa" in contract['name'].lower() or " fa-" in contract['name'].lower())) or \
            (" nda " in contract['name'].lower()) or \
                (" dpa " in contract['name'].lower() or "dpa-" in contract['name'].lower() or "fa&sow" in contract['name'].lower()):
        return        
    
    searchTxt = (contract['name'] +  " " + contract['description']).lower()
    ignore = ["dpa",
              "nda",
              "feedback agreement",
              "service agreement",
              "confidentialityagreement",
              "confidentiality agreement"
              "sap fa",
              "sow-",
              "dpa-",
              ]
    
    for i in ignore:
        if (" " + i + " " in searchTxt) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            return
        
    
    tagsToAdd = []
        
    isSoW = False
    isUnclassified = True
    isSupport = False
    isLicense = False
    isHardware = False
    isTelephony = False 

    searches = [
        "sow",
        "sow&fa",
        "statement of work",
        "delivery",
        "implementation",
        "project",
        "consulting",
        "consultancy",
        "consultant",
        "consultants",
        "consultancy services",
    ]

    for i in searches:
        if (" " + i + " " in searchTxt.replace("_", " ")) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            isSoW = True
            isUnclassified = False
            break

    searches = [
        "support",
        "maintenance",
        "helpdesk",
        "hours",
        "service",
        "sla",
        "support",
        "supporting"
    ]

    for i in searches:
        if (" " + i + " " in searchTxt) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            isSupport = True
            isUnclassified = False
            isSow = False
            break

    searches = [
        "license",
        "users",
        "software",
        "saas",
        "subscription",
        "tool"
    ]

    for i in searches:
        if (" " + i + " " in searchTxt) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            isLicense = True
            isSow = False
            isUnclassified = False
            isSupport = False
            break

    
    searches = [
        "hardware",
        "servers",
        "device",
        "server",
        "devices",
        "network",
        "switch",
        "router",
        "firewall",
        "storage",
        "datacenter",
        "data center",
        "datacentre",
        "printing",
        "printer",
        "printers",
        "laptop",
        "desktop",
        "workstation",
        "workstations",
        "monitor",
        "monitors",
        "display",
        "displays",
        "keyboard",
        "keyboards"                     
    ]

    print(contract['supplier'], contract['name'])

 
    for i in searches:
        if (" " + i + " " in searchTxt) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            isLicense = False
            isSow = False
            isUnclassified = False
            isSupport = False
            isTelephony = False
            isHardware = True
            break


    searches = [
        "telephony",
        "telephone",    
        "telecom",
        "telecommunications",        
        "communications",
        "phone",
        "voip",
        "mobile",
        "fixed line",
        "fixedline"
    ]

    
    for i in searches:
        if (i  in searchTxt.lower()) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            isLicense = False
            isSow = False
            isUnclassified = False
            isSupport = False
            isHardware = False
            isTelephony= True
            break


    telephonySuppliers = ["orange", "vodafone", "t-mobile", "telefonica", "kpn", "tele2", "british telecom"]

    for i in telephonySuppliers:
        if i in contract['supplier'].lower() + " " + contract['name'].lower():
            isLicense = False
            isSow = False
            isUnclassified = False
            isSupport = False
            isHardware = False
            isTelephony= True


    if not isSoW and not isLicense and not isSupport and not isHardware and not isTelephony:
        isUnclassified = True


    if isSoW:
        tagsToAdd.append(default_tags['sow'])
    elif isLicense:
        tagsToAdd.append(default_tags['license'])
    elif isSupport:
        tagsToAdd.append(default_tags['support'])
    elif isHardware:
        tagsToAdd.append(default_tags['hardware'])
    elif isTelephony:
        tagsToAdd.append(default_tags['telephony'])
    else:
        tagsToAdd.append(default_tags['unclassified'])


    contractName = contract['name']

    app,domains = detectApp(contract['name'], contract['supplier'])

    if app is None:
        app,domains = detectApp(contract['description'], contract['supplier'])

    title = sanitize_title(contractName)
    #append start and end dates

    if contract['start-date'] is not None and contract['end-date'] is not None:
        title += " (" + contract['start-date'] + " - " + contract['end-date'] + ")"

    # title.replace(contract["supplier"], "")
    title = contract["supplier"].replace("_", " ") + " " + title #+ " #" + str(contract["coupa_contract_id"])

    title = title.replace(contract["supplier"] + " " + contract["supplier"], contract["supplier"])

    if contract['description'] == "Legacy Contract":
        contract['description'] = ""

    noticeDate = None
    if contract['end-date'] is not None:
        #noticeDate is end date minus 6 months. convert to timestamp then deduct 6 months render as YYYY-MM-DD
        noticeDate = datetime.datetime.strptime(contract['end-date'], '%Y-%m-%d') - datetime.timedelta(days=180)
        noticeDate = noticeDate.strftime('%Y-%m-%d')      


    
    if contract['start-date'] is None:
        return

    print(contract)

    try:

        contract_id = leanix_api.create_contract(\
            name=title,\
            supplierName=contract["supplier"],\
            description=contract["description"],\
            subtype="Amendment" if contract["amendment"] else "MasterContract",\
            isActive=True,\
            isExpired=False,\
            contractValue=contract["min-commitment-eur"],\
            numberOfSeats=None,\
            volumeType="License",\
            eol_date=contract['end-date'],\
            active_date=contract['start-date'],\
            phasein_date=None,\
            notice_date=noticeDate,\
            externalId=contract["coupa_contract_id"],\
            externalUrl=contract["url"],\
            applicationId=app,\
            domains=domains,\
            managedByName=contract['owner_fullname'],\
            managedByEmail=contract['owner_mail'],\
            currency=contract['currency'],\
            additionalTags=tagsToAdd
        )

        print(contract_id)

        file = contract['document']

        if file is not None:
            basename = os.path.basename(file)
            leanix_api.upload_resource_to_factsheet(contract_id, file, basename, "documentation", "Contract document")
    
    except Exception as e:
        print("ERROR - " + title)
        print(e)
    
    print("OK - " + title)

    
    


if __name__ == "__main__":
    coupa_domain = '<tenant>.coupahost.com' 
    client_id = '<clientid>'
    client_secret = '<secret>'

    coupa_api = CoupaAPI(domain=coupa_domain, client_id=client_id, client_secret=client_secret, verify_ssl=False)
    coupa_api.obtain_access_token()

    leanix_token = '<token>'
    leanix_auth_url = 'https://<tenant>.leanix.net/services/mtm/v1/oauth2/token'
    leanix_request_url = 'https://<tenant>.leanix.net/services/pathfinder/v1/graphql'

    leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url)

    contracts = leanix_api.get_all("Contract")

    #extract id only
    contract_ids_to_exclude = []

    for c in contracts:
        id = c['externalId']

        if id is not None:
            contract_ids_to_exclude.append(id)


    all_tags = leanix_api.all_tags()

    #find tag id  with name = "Support"

    default_tags = {}
    default_tags['support'] = None
    default_tags['unclassified'] = None
    default_tags['license'] = None
    default_tags['sow'] = None    
    default_tags['hardware'] = None    
    default_tags['telephony'] = None    

    for tag in all_tags:
        tag = tag['node']

        if tag['name'] == "Support":
            default_tags['support'] = tag['id'] 

        elif tag['name'] == "Unclassified":
            default_tags['unclassified'] = tag['id']

        elif tag['name'] == "SoW":
            default_tags['sow'] = tag['id']
            
        elif tag['name'] == "License":
            default_tags['license'] = tag['id']

        elif tag['name'] == "Hardware":
            default_tags['hardware'] = tag['id']

        elif tag['name'] == "Telephony":
            default_tags['telephony'] = tag['id']
            
        else:
            pass
    
    
    
    coupa_api.get_all_contracts(callback=parseContract, excludeId=contract_ids_to_exclude, filteringCategory=124452)
    
    # leanix_api.delete_contracts_with_tag(default_tags["unclassified"])

            
