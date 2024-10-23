from akamai.edgegrid import EdgeGridAuth
import urllib.parse
import sys
import datetime
import requests

class AkamaiAPI:
    """
    Class to interact with the Akamai API and retrieve traffic reports
    """
    cache = {}  # cache for (expensive) API responses

    def __init__(self, client_token, client_secret, access_token, base_url):
        self.client_token = client_token
        self.client_secret = client_secret
        self.access_token = access_token
        self.base_url = base_url
        self.session = requests.Session()
        self.session.auth = EdgeGridAuth(
            client_token=self.client_token,
            client_secret=self.client_secret,
            access_token=self.access_token
        )

    def _call(self, method, endpoint, params=None, data=None):
        """
        Returns the JSON response from the Akamai v2 Report API (v1 decommed by Jan 2025)
        """
        url = urllib.parse.urljoin(self.base_url, endpoint)
        response = self.session.request(method, url, params=params, json=data)

        if response.status_code != 200:
            print(f"Error calling {method} {url}: {response.status_code}", file=sys.stderr)
            print(response.text)
            return None
        
        return response.json()
    
    def get_time_window(self, sinceDaysAgo):
        """
        Returns the start and end date for the time window based on the number of days ago
        """
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        startDate = (yesterday - datetime.timedelta(days=sinceDaysAgo)).strftime('%Y-%m-%d')

        return startDate, yesterday
    
    def get_traffic(self, sinceDaysAgo=30, includeTimeDimension=True):
        """
        Returns the traffic report for the last {sinceDaysAgo} days grouped by hits, bytes and offloaded percentage
        """    
        #calculate: endDate = today, startDate = today - 30 days
        startDate, endDate = self.get_time_window(sinceDaysAgo)

        cacheKey = f"traffic-report-" + str(includeTimeDimension)

        payload = {
                    "dimensions": [
                        "hostname", 
                        "cpcode"
                    ],
                    "metrics": [
                        "edgeHitsSum",
                        "edgeBytesSum",
                        "offloadedHitsPercentage",
                        "offloadedBytesPercentage"
                    ],
                    "sortBys": [
                    {
                        "name": "edgeHitsSum",
                        "sortOrder": "DESCENDING"
                    }
                    ]
                }

        if includeTimeDimension:
            payload["dimensions"].append("time1day")

        self.cache[cacheKey] = self._call('POST', f'/reporting-api/v2/reports/delivery/traffic/current/data?start={startDate}T00:00:00Z&end={endDate}T23:59:59Z', 
                                                data = payload)
        return self.cache[cacheKey]
    
    def get_sites_by_cpcode(self):
        """
        Returns a dictionary of sites grouped by Akamai cpcode baseed on the traffic report
        """
        if 'traffic-report' not in self.cache:
            self.get_traffic()

        sites = {}

        if "data" in self.cache['traffic-report']:
            for entry in self.cache['traffic-report']["data"]:
                if entry["hostname"] != "Others" and entry["hostname"] != "N/A":
                    if entry["cpcode"] not in sites:
                        sites[entry["cpcode"]] = []

                    if entry["hostname"] not in sites[entry["cpcode"]]:
                        sites[entry["cpcode"]].append(entry["hostname"])

        self.cache['sites-by-cpcode'] = sites

        return sites
    
    def get_metrics_by_hostname(self, factsheetId=None, hostname=None, includeTimeDimension=True, sinceDaysAgo=30):
        """
        Returns the metrics for a given hostname
        """
        cacheKey = f"traffic-report-" + str(includeTimeDimension)
        if cacheKey not in self.cache:
            self.get_traffic(includeTimeDimension=includeTimeDimension, sinceDaysAgo=sinceDaysAgo)

        metrics = []

        MB = 1024*1024

        if "data" in self.cache[cacheKey]:
            for entry in self.cache[cacheKey]["data"]:
                if entry["hostname"] == hostname:
                    
                    metric = {
                        "hostname": entry["hostname"],
                        "cpcode": "CP Code: " + str(entry["cpcode"]),
                        "edgeBytesSum": int(entry["edgeBytesSum"]/MB),
                        "edgeHitsSum": entry["edgeHitsSum"],
                        "offloadedBytesPercentage": round(float(entry["offloadedBytesPercentage"]), 2),
                        "offloadedHitsPercentage": round(float(entry["offloadedHitsPercentage"]), 2),
                    }                    

                    if includeTimeDimension:
                        metric["factSheetId"] = factsheetId
                        metric["timestamp"] = int(entry["time1day"])

                    metrics.append(metric)

        return metrics
    
