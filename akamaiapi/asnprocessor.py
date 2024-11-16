import requests
import re
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class ASNProcessor:
    def __init__(self, output_csv="asn_organizations.csv", thread_count=5, loadFromFile=False):
        self.output_csv = output_csv
        self.iana_url = "https://www.iana.org/assignments/as-numbers/as-numbers-1.csv"
        self.graphql_api = "https://api.asrank.caida.org/v2/graphql"
        self.thread_count = thread_count
        self.asn_dict = {}

        if not loadFromFile:
            # Ensure the CSV has a header row if it doesn't exist
            try:
                with open(self.output_csv, "x", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    writer.writerow(["asn", "org_name"])  # Header row
            except FileExistsError:
                pass
        else:
            self.download_csv("https://raw.githubusercontent.com/cwittenberg/leanix/main/akamaiapi/asn_organizations.csv")
            self.load_csv_to_memory()

    def fetch_iana_asns(self):
        """Fetch ASNs from the IANA ASN registry."""
        response = requests.get(self.iana_url)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch IANA ASN registry: {response.status_code}")

        data = response.text
        asns = []

        # Parse the CSV content
        for line in data.splitlines():
            match = re.match(r"^(\d+)(?:-(\d+))?,(.+)", line)
            if match:
                asn_start = int(match.group(1))
                asn_end = int(match.group(2)) if match.group(2) else asn_start

                # Expand ASN ranges
                for asn in range(asn_start, asn_end + 1):
                    asns.append(asn)

        return asns

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException)
    )
    def fetch_asn_organization(self, asn):
        """Fetch the organization name for a given ASN from the CAIDA AS Rank GraphQL API."""
        query = {
            "query": f"""
            {{
               asn(asn:"{asn}") {{
                  organization {{
                     orgName
                  }}
               }}
            }}
            """
        }
        response = requests.post(self.graphql_api, json=query)
        response.raise_for_status()

        data = response.json()
        return data.get("data", {}).get("asn", {}).get("organization", {}).get("orgName", None)

    def append_to_csv(self, asn, org_name):
        """Append ASN and organization name to the CSV file."""
        with open(self.output_csv, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([asn, org_name])

    def process_asn(self, asn):
        """Worker function to process a single ASN."""
        try:
            org_name = self.fetch_asn_organization(asn)
            if org_name:
                self.append_to_csv(asn, org_name)
                self.asn_dict[asn] = org_name  # Add to in-memory dictionary
            print(f"ASN {asn} processed: {org_name}")
        except Exception as e:
            print(f"Error processing ASN {asn}: {e}")

    def process_asns_multithreaded(self, asns):
        """Process ASNs using a thread pool for parallel processing."""
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            futures = [executor.submit(self.process_asn, asn) for asn in asns]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error in thread: {e}")

    def load_csv_to_memory(self):
        """Load the CSV file into memory as a dictionary for efficient lookup."""
        with open(self.output_csv, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                asn = int(row["asn"])  # Convert ASN to integer for fast lookups
                org_name = row["org_name"]
                self.asn_dict[asn] = org_name
        print(f"Loaded {len(self.asn_dict)} records into memory.")

    def get_org_name(self, asn):
        """Retrieve the organization name for a given ASN from the in-memory dictionary."""
        return self.asn_dict.get(asn, "Organization not found")

    def run(self):
        """Main function to fetch ASNs and process them in parallel."""
        print("Fetching ASNs from IANA...")
        asns = self.fetch_iana_asns()

        print(f"Total ASNs to process: {len(asns)}")
        print(f"Running with {self.thread_count} threads...")
        self.process_asns_multithreaded(asns)
        print("ASN processing complete.")
        self.load_csv_to_memory()

    
    def download_csv(self, url, output_file=None):
        """Download a CSV file from a URL and save it locally."""
        output_file = output_file or self.output_csv
        response = requests.get(url)
        if response.status_code == 200:
            with open(output_file, mode="wb") as file:
                file.write(response.content)
            print(f"Downloaded CSV from {url} to {output_file}")
        else:
            raise Exception(f"Failed to download CSV file: {response.status_code}")



# if __name__ == "__main__":
#     processor = ASNProcessor(loadFromFile=True)

#     # Example usage to rerun the processor (Caida):
#     # processor.run()

#     print(processor.get_org_name(15169))  # Example ASN
