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
 
    #skip contracts where no value is known and no lifecycle dates are present
    if (contract['max-commitment'] == 0 and contract['start-date'] is None) or \
        ("service agreement" in contract['name'].lower()) or \
        (" fa:" in contract['name'].lower()) or \
        ("feedback agreement" in contract['name'].lower() or "sap fa" in contract['name'].lower() or " fa-" in contract['name'].lower()) or \
            (" nda " in contract['name'].lower()) or \
                (" sow " in contract['name'].lower() or " sow-" in contract['name'].lower()) or \
                    (" dpa " in contract['name'].lower() or "dpa-" in contract['name'].lower() or "fa&sow" in contract['name'].lower()):
        return        
    
    searchTxt = (contract['name'] +  " " + contract['description']).lower()
    ignore = ["dpa",
              "nda",
              "sow",
              "fa",
              "feedback agreement",
              "service agreement",
              "confidentialityagreement",
              "confidentiality agreement"
              "sap fa",
              "fa-",
              "sow-",
              "dpa-",
              "fa&sow"
              ]
    
    for i in ignore:
        if (" " + i + " " in searchTxt) or (" " + i + "-" in searchTxt) or (" " + i + ":" in searchTxt):
            return


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
            currency=contract['currency']
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

    coupa_domain = '<your tenant>.coupahost.com' 
    client_id = '<your client>'
    client_secret = '<your secret>'


    coupa_api = CoupaAPI(domain=coupa_domain, client_id=client_id, client_secret=client_secret, verify_ssl=False)
    coupa_api.obtain_access_token()

    leanix_token = '<your api key>'
    leanix_auth_url = 'https://<your-tenant>.leanix.net/services/mtm/v1/oauth2/token'
    leanix_request_url = 'https://<your-tenant>.leanix.net/services/pathfinder/v1/graphql'

    leanix_api = LeanIXAPI(leanix_token, leanix_auth_url, leanix_request_url)



    coupa_api.get_all_purchase_orders_by_commodity(callback=parseContract)


    # leanix_api.delete_contracts_with_coupa_tag()
