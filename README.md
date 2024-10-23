# leanix

## Simple facade to integrate Python with LeanIX
See "leanix/leanix.py"

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


## Events
Purpose:
- Send adaptivecard in Teams to update your team of a change made within LeanIX

Features:
- User/avatar retrieval from within LeanIX
- No need to use LeanIX dedicated Teams app

  ![image](https://github.com/user-attachments/assets/f2ad94f5-e964-489d-9cd1-3b09fbadb4b1)

