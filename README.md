# leanix
Advanced Python based integration with LeanIX, because you need flexibility.
- I use it with Azure Automation to enable scheduled execution of the code. See azure-automation-jobs folder for the procedural logic invoking any of the modules here.

## Simple facade to integrate Python with LeanIX
See [leanix/leanix.py](./leanix/leanix.py)

Purpose:
- Easy interoperability between Python and the LeanIX graphQL API - without having to code lots of GraphQL yourself.

Features:
- Create/update/archive factsheets
- Adding tags
- Create contracts (if you have the Contract customization enabled)
- Facilitates re-authentication/retry when needed
- Search in factsheets
- Creating relations between factsheets, dynamically
- Management of Resources to factsheets
- Create metrics/schema's
- Get SaaS discovery intelligence (i.e. for Zscaler integration)

## Generate IT Components based on Azure
Purpose:
- Why integrate with ServiceNow or other CMDBs if you can generate parts of your metamodel based on what is instantiated/consumed on Azure?

Features:
- Integration with Azure Graph
- Integration with Azure Cost Management API
- Generates IT Component structure based on Resource Groups

TODO:
- [ ] Integration with GPT4o to auto-generate Modules to a given application

## Celonis Process Modeler integration
See:
[celonis/celonis.py](./celonis/celonis.py) and the following Python Runbooks: [leanix-celonis-integration.py](./azure-automation-jobs/leanix-celonis-integration.py) and [leanix-celonis-bpmn-integration.py](./azure-automation-jobs/leanix-celonis-bpmn-integration.py)

Purpose:
- Loads all BPMN Processes from Celonis (formerly known as Symbio) into LeanIX for mapping.
- Link your Applications to your Processes, including BPMN diagrams - in the same way how SAP does this with Signavio integration - but then for Celonis/Symbio!
- Communicate to your Process Owners how IT is realizing their Processes.

How it works:
- Based on Celonis/Symbio v2 API loads process structure in memory
- Runs through this and copies each logical process as Business Context (process category) into LeanIX
- Adds BPMN diagram itself (as PNG and SVG) as Resource to each Process, including hyperlinks to Symbio.
- You can create a custom portal showing the BPMN diagrams.

![image](https://github.com/user-attachments/assets/eac1074e-ceac-488e-91ff-e96a1f54331d)
![image](https://github.com/user-attachments/assets/7618f667-b72b-48d7-a9d0-a0db82c5dd6f)


## Coupa integration
Purpose:
- Load contracts from Coupa into LeanIX such that Architects/those responsible can receive notifications about when an opportunity arises to make a (commercial) transition in view of roadmap

How it works:
- Facilitates initial load, since standard Coupa API does not filter on custom-fields that contain granular commodity codes (as is common practice), approach taken is to pull all POs from a granular IT category
- Based on Suppliers found from all POs in the granular commodity category, all contracts are pulled pertaining to each supplier
- Sanitized Contracts are uploaded to LeanIX via GraphQL

Features:
- Rudimentary auto-detection for existing Applications and Providers in LeanIX metamodel during load
- Auto-detection of Amendment vs Contract factsheet sub-types
- Facilitates currency conversion for contracts in non-group currency (i.e. EUR)
- Downloads contracts zipfile from Coupa, unzips and uploads PDF as Resource to Contract
- Also does some hard-coded tenant-specific matching of i.e. hardware/telephony/statements of work and licenses (later is relevant)

Scheduling:
- Can be scheduled in Azure Automation, make sure to add required packages as wheel (.whl)
- Dependencies for runbook: gql, requests_toolbelt, tenacity

TODO: 
- [ ] Update IT Components with Cost from contracts

Used resources:
- https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/the-coupa-core-api/resources/transactional-resources/contracts-api-(contracts)
- https://docs-eam.leanix.net/reference/example-queries-and-mutations
- https://exchangeratesapi.io/

![image](https://github.com/user-attachments/assets/d7690ba6-0186-43d0-bccd-57f4a3483508)

## Akamai integration
Purpose:
- Lifecycle your websites, just like you would applications.

How it works:
- Integrates with Akamai Report API v2 to pull all websites
- Loads Metrics (hits and CDN effectiveness %) into LeanIX

Features:
- Grouping by Akamai CP code
- Show # hits, bandwidth and CDN offload % as a timeseries for decision making

Generated factsheets (note also past 90 day summary on main factsheet, for easy sorting in Inventory)
![image](https://github.com/user-attachments/assets/e469c522-aff6-42c8-96d1-a8bc6fce5fc6)

Metrics tab:
![image](https://github.com/user-attachments/assets/60848a73-ecbe-4a47-9cf2-34a1b5531d69)

## Zscaler usage metrics by app
See [leanix/leanix.py](./leanix/leanix.py) (discovery methods) and [leanix-load-zscaler-metrics.py](./azure-automation-jobs/leanix-load-zscaler-metrics.py)

Purpose
- To lifecycle your apps, you need to know the architect's vision, cost and usage.
- Knowing how many users your apps utilize over time is a great way to support architecture decision making.

How it works:
- Utilize internal Zscaler discovery API to plot usage Metrics by application

![image](https://github.com/user-attachments/assets/e136e21b-0468-4e43-a088-c0d5dcf8be8c)


## Events
Purpose:
- Send adaptivecard in Teams to update your team of a change made within LeanIX

Features:
- User/avatar retrieval from within LeanIX
- No need to use LeanIX dedicated Teams app

  ![image](https://github.com/user-attachments/assets/f2ad94f5-e964-489d-9cd1-3b09fbadb4b1)


