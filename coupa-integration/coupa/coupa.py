import time
import requests
import json
import re
import warnings
import os
import zipfile
from urllib3.exceptions import InsecureRequestWarning

from datetime import datetime

# Suppress only the InsecureRequestWarning from urllib3
warnings.simplefilter('ignore', InsecureRequestWarning)

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

# Set up logging to see the retry attempts
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)



class CoupaAPI:
    _exchange_rates = []
    _rate_token = "" #<add token here> for exchangeratesapi.io

    def __init__(self, domain, client_id, client_secret, verify_ssl=True):
        self.domain = domain
        self.client_id = client_id
        self.client_secret = client_secret
        self.verify_ssl = verify_ssl
        self.access_token = None

    def get_date(self, date_str):
        dt = datetime.fromisoformat(date_str).date()
        return dt.strftime('%Y-%m-%d')
    
    def get_rates(self):
        try: 
            url =f"https://api.exchangeratesapi.io/v1/latest?access_key={self._rate_token}&format=1"
            rates = self._call(url).json()

            #write rates to file
            with open('rates.json', 'w') as f:
                f.write(json.dumps(rates, indent=4))
        except:

            #read rates from file
            with open('rates.json', 'r') as f:
                rates = json.load(f)

        self._exchange_rates = rates['rates']

        return rates
    
    def convert_to_eur(self, amount, currency):
        if self._exchange_rates == []:
            self.get_rates()

        #ensure amount is a float
        amount = float(amount)

        """Converts the given amount in the specified currency to EUR."""
        if currency == "EUR" or currency == "" or currency is None:
            return amount
        if currency not in self._exchange_rates:
            raise ValueError(f"Currency {currency} not supported")
        rate = self._exchange_rates[currency]
        val = amount / rate

        #rount to two decimal places
        return round(val, 2)

    def obtain_access_token(self):
        """Obtain an OAuth access token using the client credentials grant type."""
        token_url = f'https://{self.domain}/oauth2/token'
        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'core.contract.read core.contracts_template.read core.purchase_order.read'
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(token_url, data=payload, headers=headers, verify=self.verify_ssl)

        if response.status_code == 200:
            self.access_token = response.json().get('access_token')
            print(f"Access Token obtained: {self.access_token}")
        else:
            print(f"Failed to obtain token: {response.status_code}")
            print(f"Response: {response.text}")
            raise Exception("Failed to obtain access token")

        return self.access_token
    

    def harmonize_company_name(company_name):
        # Define a regex pattern to match common company suffixes
        pattern = r'\b(b\.v\.|n\.v\.|inc\.|incorporated|llc|ltd|limited|corp\.|corporation|gmbh|ag|s\.a\.|pvt\.|plc|co\.|company|s\.r\.l\.|pte\. ltd\.)\b'
        
        # Remove matching suffixes, ignoring case
        harmonized_name = re.sub(pattern, '', company_name, flags=re.IGNORECASE)

        # Remove any leading or trailing whitespace
        harmonized_name = harmonized_name.strip()

        # Normalize multiple spaces to a single space
        harmonized_name = re.sub(r'\s+', ' ', harmonized_name)
        
        return harmonized_name

    def get_po_companies(self):
        url = 'https://akzonobel.coupahost.com/api/purchase_order_lines?commodity[id]=1039&commodity[name]=IT Software and Maintenance - L4&fields=["description", "created-at", "updated-at", {"supplier": ["id", "name"]}]'
        
        
        #iterate throguh applicable contracts - if so existing
        supplier_id=1200
        url = f'https://akzonobel.coupahost.com/api/contracts?fields=["id", "created-at", "updated-at", "name","description","type","min-commit", "max-commit", "term-type"]&status=published&supplier[id]={supplier_id}'

    @retry(
        stop=stop_after_attempt(3),  # Stop after 5 attempts
        wait=wait_exponential(multiplier=1, min=2, max=60),  # Exponential backoff: wait 2^x * 1 (where x is the attempt number)
        retry=retry_if_exception_type(requests.exceptions.RequestException),  # Retry on any requests exceptions
        before_sleep=before_sleep_log(logger, logging.INFO)  # Log before retrying
    )
    def _call(self, url, params=None, operation="GET", data=None):
        if not self.access_token:
            raise Exception("Access token not available. Call obtain_access_token() first.")

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }

        if operation == "GET":
            response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        elif operation == "POST":
            response = requests.post(url, headers=headers, json=data, verify=self.verify_ssl)
        elif operation == "PUT":
            response = requests.put(url, headers=headers, json=data, verify=self.verify_ssl)
        elif operation == "DELETE":
            response = requests.delete(url, headers=headers, verify=self.verify_ssl)
        else:
            raise Exception("Unsupported HTTP operation")
        
        return response

    def get_all_contracts(self,limit=50):
        """Retrieve all contracts with pagination until none are left."""
        if not self.access_token:
            raise Exception("Access token not available. Call obtain_access_token() first.")

        all_contracts = []
        offset = 0

        while True:
            contracts_url = f'https://{self.domain}/api/contracts?status=published'
            

            params = {
                'offset': offset,
                'limit': limit
            }

            response = self._call(contracts_url, params=params)

            if response.status_code == 200:
                contracts = response.json()

                if not contracts:
                    break  # No more contracts to retrieve

                all_contracts.extend(contracts)
                offset += limit
            else:
                print(f"Failed to retrieve contracts: {response.status_code}")
                print(f"Response: {response.text}")
                break

        return all_contracts

    

    def get_contracts_by_supplier(self, supplier_id, max_commit=None, offset=0, limit=50):
        """Retrieve contracts with pagination."""
        if not self.access_token:
            raise Exception("Access token not available. Call obtain_access_token() first.")

        # contracts_url = f'https://{self.domain}' + '/api/contracts?status=published&fields=["start-date","end-date","id", "created-at", "updated-at", "name","description","type","min-commit", "max-commit", "term-type", {"currency":["code"]}]&status=published&supplier[id]=' + str(supplier_id)
        
        contracts_url = f'https://{self.domain}' + '/api/contracts?status=published&supplier[id]=' + str(supplier_id)
        
        if max_commit is not None:
            contracts_url += '&max-commit[in]=' + str(max_commit)

        #contracts_url = f"https://{self.domain}/api/contracts?status=published"
        # headers = {
        #     'Authorization': f'Bearer {self.access_token}',
        #     'Accept': 'application/json'
        # }
        params = {
            'offset': offset,
            'limit': limit
        }
        # response = requests.get(contracts_url, headers=headers, params=params, verify=self.verify_ssl)
        response = self._call(contracts_url, params=params)

        if response.status_code == 200:
            contracts = response.json()
            return contracts
        else:
            print(f"Failed to retrieve contracts: {response.status_code}")
            print(f"Response: {response.text}")
            return []
        
    
    def extract_first_pdf(self, zip_file_path, output_dir):
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            # List all files in the ZIP archive
            file_list = zip_ref.namelist()

            # Find the first PDF file
            for file_name in file_list:
                if file_name.endswith('.pdf'):
                    # Extract the first PDF file
                    zip_ref.extract(file_name, output_dir)
                    print(f"Extracted: {file_name}")
                    return os.path.join(output_dir, file_name)
            
            print("No PDF file found in the archive.")
            return None
    
    def get_document(self, contract_id):
        """Retrieve contract pdfs."""
        if not self.access_token:
            raise Exception("Access token not available. Call obtain_access_token() first.")

        contracts_url = f"https://{self.domain}/api/contracts/{contract_id}/retrieve_legal_agreement"
        # headers = {
        #     'Authorization': f'Bearer {self.access_token}',
        #     'Accept': 'application/json'
        # }

        #download file and save to disk (can be a large pdf)
        # response = requests.get(contracts_url, headers=headers, verify=self.verify_ssl)
        response = self._call(contracts_url)

        docFile = f'docs/contract_{contract_id}.zip'

        if response.status_code == 200:
            with open(docFile, 'wb') as f:
                f.write(response.content)

            #mkdir contract_id
            
            #os path indicator
            sep = os.path.sep

            try:
                os.makedirs('docs' + sep + str(contract_id), exist_ok=True)
                pdfFile = self.extract_first_pdf(docFile, 'docs' + sep + str(contract_id))
                
                docFile = pdfFile
            except Exception as e:
                print(f"Failed to extract PDF file: {e}")
                docFile = None

        else:
            if response.status_code == 404:
                print(f"Document not found for contract: {contract_id}")
                docFile = None
                return False
            else:
                print(f"Failed to retrieve document: {response.status_code}")
                docFile = None
                print(f"Response: {response.text}")
            
        return docFile

    
    def get_purchase_orders_by_commodity(self, commodity_name, offset=0, limit=50):
        """Retrieve purchase orders filtered by commodity with pagination."""
        if not self.access_token:
            raise Exception("Access token not available. Call obtain_access_token() first.")
        
        # fields = '[{"custom_fields": ["long-description"]},{"currency": ["code"]},"accounting-total","account-type","description", "created-at", "updated-at", {"supplier": ["id", "name"]}]'
        fields = '["created-at", "updated-at", {"supplier": ["id", "name"]}]'

        purchase_orders_url = f'https://{self.domain}/api/purchase_order_lines?commodity[name]={commodity_name}' + '&fields=' + fields
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        params = {
            'offset': offset,
            'limit': limit
        }

        # response = requests.get(purchase_orders_url, headers=headers, params=params, verify=self.verify_ssl)
        response = self._call(purchase_orders_url, params=params)

        if response.status_code == 200:
            purchase_orders = response.json()
            return purchase_orders
        else:
            print(f"Failed to retrieve purchase orders: {response.status_code}")
            print(f"Response: {response.text}")
            return []

    def get_all_purchase_orders_by_commodity(self, commodity_name="IT Software and Maintenance - L4", callback=None):
        """Retrieve all purchase orders for a given commodity by handling pagination."""
        all_purchase_orders = []
        offset = 0
        limit = 50

        # enabled = False

        while True:
            purchase_orders = self.get_purchase_orders_by_commodity(commodity_name, offset, limit)
            if not purchase_orders:
                break
            all_purchase_orders.extend(purchase_orders)
            if len(purchase_orders) < limit:
                break
            offset += limit
            time.sleep(1)  # To avoid hitting rate limits

            for po in purchase_orders:
                print(po['supplier']['name'])

                # if po['supplier']['name'] == "ServiceNow Nederland B.V.":
                #     enabled=True

                # if enabled:
                self.get_all_contracts_by_supplier(po['supplier']['id'], callback)

        return all_purchase_orders

    
    def filter_contracts(self, contracts):
        filtered = []

        for contract in self.filter_contracts(contracts):
            if contract['custom-fields'] is not None:
                if contract['custom-fields']['categories-applicable'] is not None:
                    for field in contract['custom-fields']['categories-applicable']:                            
                        if field['id'] in (124452, 107635):
                            if ' nda' not in contract['name'].lower() and '_nda' not in contract['name'].lower() and \
                                contract['type'] in ('MasterAgreement', 'SourcingAgreement', 'ServiceAgreement', 'SupplierAgreement', 'VendorAgreement', 'Contract') and \
                                contract['status'] != 'expired':

                                filtered.append(contract)

        return filtered


    def get_all_contracts_by_supplier(self, supplier_id, callback=None):
        """Retrieve all contract IDs by iterating through all pages."""
        offset = 0
        limit = 50
        all_contract_ids = []

        while True:
            contracts = self.get_contracts_by_supplier(supplier_id, offset=offset, limit=limit)     

            if not contracts or len(contracts) == 0:
                break  # Exit loop if no more contracts are returned

            #write it to file as formatted json
            # for contract in self.filter_contracts(contracts):
            for contract in contracts:
                                        
                print(f"Contract ID: {contract['id']}, Contract Type: {contract['name']}, Category")

                docFile = None

                try:
                        docFile = self.get_document(contract['id'])

                        if docFile == False:
                            docFile = None
                except:
                    docFile = None


                lower = contract['name'].lower()
                isAmendment = 'renewal' in lower or 'extension' in lower or 'amendment' in lower or 'addendum' in lower or 'revised' in lower or 'renewed' in lower or 'renew' in lower

                #check if docFile is larger than 10mb, if so, then set to None
                #(leanix cannot handle those large files)
                if docFile is not None:
                    if os.path.getsize(docFile) > 10*1024*1024:
                        docFile = None

                c = {
                    'coupa_contract_id': contract['id'],
                    'coupa_supplier_id': supplier_id,
                    'name': contract['name'],
                    'type': contract['type'],
                    'owner_mail': contract['contract-owner']['email'],
                    'owner_fullname': contract['contract-owner']['fullname'],
                    'start-date': self.get_date( contract['start-date'] ),
                    'end-date': self.get_date( contract['end-date'] ),
                    'supplier': contract['supplier']['custom-fields']['harmonized-supplier-name'],
                    'currency': contract['currency']['code'],
                    'TCV': contract['custom-fields']['total-contract-value-in-eur'],
                    'min-commitment': contract['min-commit'],
                    'max-commitment': contract['max-commit'],
                    'min-commitment-eur': self.convert_to_eur(contract['min-commit'], contract['currency']['code'].upper()),
                    'max-commitment-eur': self.convert_to_eur(contract['max-commit'], contract['currency']['code'].upper()),
                    'description': contract['description'],
                    'document': docFile,
                    'amendment': isAmendment,
                    'url': contract['legal-agreement-url']
                }

                #make supplier path safe
                fileSupplier = c['supplier'] = re.sub(r'[^a-zA-Z0-9]', '_', c['supplier'])

                with open(f'contracts-{fileSupplier}-{c['coupa_contract_id']}.json', 'w') as f:
                    f.write(json.dumps(c, indent=4))

                
                # if "SCT" in c['name'] or "SuccessFactors" in c['name']:
                if callback is not None:
                    callback(c)

                        # exit()
                
            all_contract_ids.extend([contract['id'] for contract in contracts])
            offset += limit

            #sleep for 5 seconds
            time.sleep(1)
